#!/usr/bin/env python
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2012 thomasv@ecdsa.org
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.


import os
import util
from bitcoin import *

USE_DIFF_RETARGET = True

class Blockchain(util.PrintError):
    '''Manages blockchain headers and their verification'''
    def __init__(self, config, network):
        self.config = config
        self.network = network
        self.local_height = 0
        # No URL for Groestlcoin
        self.headers_url = ''#'http://headers.electrum.org/blockchain_headers'
        self.set_local_height()

    def height(self):
        return self.local_height

    def init(self):
        self.init_headers_file()
        self.set_local_height()
        self.print_error("%d blocks" % self.local_height)

    def verify_chain(self, chain):
        first_header = chain[0]
        prev_header = self.read_header(first_header.get('block_height') -1)

        for header in chain:
            height = header.get('block_height')
            prev_hash = self.hash_header(prev_header)
            if height >= 100000:
                bits, target = self.get_target(height, chain)
            _hash = self.hash_header(header)
            try:
                assert prev_hash == header.get('prev_block_hash')
                if height >= 100000:
                    assert bits == header.get('bits')
                    assert int('0x'+_hash,16) < target
            except Exception:
                return False

            prev_header = header

        return True



    def verify_chunk(self, index, hexdata):
        data = hexdata.decode('hex')
        height = index*2016
        num = len(data)/80

        if index == 0:
            previous_hash = ("0"*64)
        else:
            prev_header = self.read_header(index*2016-1)
            if prev_header is None: raise
            previous_hash = self.hash_header(prev_header)

        #bits, target = self.get_target(index)

        for i in range(num):
            height = index*2016 + i
            raw_header = data[i*80:(i+1)*80]
            header = self.header_from_string(raw_header)
            _hash = self.hash_header(header)
            assert previous_hash == header.get('prev_block_hash')
            # If using diff retarget, calculate/verify bits
            if USE_DIFF_RETARGET and height >= 100000:
                bits, target = self.get_target(height)
                assert bits == header.get('bits')
                assert int('0x'+_hash,16) < target
            if USE_DIFF_RETARGET:
                self.save_header(header, height)

            previous_header = header
            previous_hash = _hash

        if USE_DIFF_RETARGET == False:
            self.save_chunk(index, data)
        self.print_error("validated chunk %d to height %d" % (index, height))



    def header_to_string(self, res):
        s = int_to_hex(res.get('version'),4) \
            + rev_hex(res.get('prev_block_hash')) \
            + rev_hex(res.get('merkle_root')) \
            + int_to_hex(int(res.get('timestamp')),4) \
            + int_to_hex(int(res.get('bits')),4) \
            + int_to_hex(int(res.get('nonce')),4)
        return s


    def header_from_string(self, s):
        hex_to_int = lambda s: int('0x' + s[::-1].encode('hex'), 16)
        h = {}
        h['version'] = hex_to_int(s[0:4])
        h['prev_block_hash'] = hash_encode(s[4:36])
        h['merkle_root'] = hash_encode(s[36:68])
        h['timestamp'] = hex_to_int(s[68:72])
        h['bits'] = hex_to_int(s[72:76])
        h['nonce'] = hex_to_int(s[76:80])
        return h

    def hash_header(self, header):
        return rev_hex(groestlHash(self.header_to_string(header).decode('hex')).encode('hex'))

    def path(self):
        return os.path.join(self.config.path, 'blockchain_headers')

    def init_headers_file(self):
        filename = self.path()
        if os.path.exists(filename):
            return
        try:
            import urllib, socket
            socket.setdefaulttimeout(30)
            self.print_error("downloading ", self.headers_url )
            urllib.urlretrieve(self.headers_url, filename)
            self.print_error("done.")
        except Exception:
            self.print_error( "download failed. creating file", filename )
            open(filename,'wb+').close()

    def save_chunk(self, index, chunk):
        filename = self.path()
        f = open(filename,'rb+')
        f.seek(index*2016*80)
        h = f.write(chunk)
        f.close()
        self.set_local_height()

    def save_header(self, header, height=None):
        data = self.header_to_string(header).decode('hex')
        assert len(data) == 80
        if height is None: height = header.get('block_height')
        filename = self.path()
        f = open(filename,'rb+')
        f.seek(height*80)
        h = f.write(data)
        f.close()
        self.set_local_height()

    def set_local_height(self):
        name = self.path()
        if os.path.exists(name):
            h = os.path.getsize(name)/80 - 1
            if self.local_height != h:
                self.local_height = h

    def roll_back_to_last_chunk(self):
        name = self.path()
        if os.path.exists(name):
            f = open(name, 'rb+')
            f.seek( (self.local_height - 100) *80)
            f.truncate()
            f.close()
        self.set_local_height()

    def read_header(self, block_height):
        name = self.path()
        if os.path.exists(name):
            f = open(name,'rb')
            f.seek(block_height*80)
            h = f.read(80)
            f.close()
            if len(h) == 80:
                h = self.header_from_string(h)
                return h

    def bits_to_target(self, bits):
        MM = 256*256*256
        a = bits%MM
        if a < 0x8000:
            a *= 256
        target = (a) * pow(2, 8 * (bits/MM - 3))
        return target

    def target_to_bits(self, target):
        MM = 256*256*256
        c = ("%064X"%target)[2:]
        i = 31
        while c[0:2]=="00":
            c = c[2:]
            i -= 1

        c = int('0x'+c[0:6],16)
        if c >= 0x800000:
            c /= 256
            i += 1

        new_bits = c + MM * i
        return new_bits

    def get_target_dgw3(self, block_height, chain=None):
        if chain is None:
            chain = []

        last = self.read_header(block_height-1)
        if last is None:
            for h in chain:
                if h.get('block_height') == block_height-1:
                    last = h

        # params
        BlockLastSolved = last
        BlockReading = last
        BlockCreating = block_height
        nActualTimespan = 0
        LastBlockTime = 0
        PastBlocksMin = 24
        PastBlocksMax = 24
        CountBlocks = 0
        PastDifficultyAverage = 0
        PastDifficultyAveragePrev = 0
        bnNum = 0

        max_target = 0x00000FFFF0000000000000000000000000000000000000000000000000000000

        if BlockLastSolved is None or block_height-1 < PastBlocksMin:
            return 0x1e0ffff0, max_target
        for i in range(1, PastBlocksMax + 1):
            CountBlocks += 1

            if CountBlocks <= PastBlocksMin:
                if CountBlocks == 1:
                    PastDifficultyAverage = self.bits_to_target(BlockReading.get('bits'))
                else:
                    bnNum = self.bits_to_target(BlockReading.get('bits'))
                    PastDifficultyAverage = ((PastDifficultyAveragePrev * CountBlocks)+(bnNum)) / (CountBlocks + 1)
                PastDifficultyAveragePrev = PastDifficultyAverage

            if LastBlockTime > 0:
                Diff = (LastBlockTime - BlockReading.get('timestamp'))
                nActualTimespan += Diff
            LastBlockTime = BlockReading.get('timestamp')

            BlockReading = self.read_header((block_height-1) - CountBlocks)
            if BlockReading is None:
                for br in chain:
                    if br.get('block_height') == (block_height-1) - CountBlocks:
                        BlockReading = br

        bnNew = PastDifficultyAverage
        nTargetTimespan = CountBlocks * 60

        nActualTimespan = max(nActualTimespan, nTargetTimespan/3)
        nActualTimespan = min(nActualTimespan, nTargetTimespan*3)

        # retarget
        bnNew *= nActualTimespan
        bnNew /= nTargetTimespan
        bnNew = min(bnNew, max_target)

        new_bits = self.target_to_bits(bnNew)
        return new_bits, bnNew


    def get_target(self, block_height, chain=None):
        if chain is None:
            chain = []  # Do not use mutables as default values!

        # DGW3 starts at block 99,999
        assert block_height >= 100000
        return self.get_target_dgw3(block_height, chain)

    def connect_header(self, chain, header):
        '''Builds a header chain until it connects.  Returns True if it has
        successfully connected, False if verification failed, otherwise the
        height of the next header needed.'''
        chain.append(header)  # Ordered by decreasing height
        previous_height = header['block_height'] - 1
        previous_header = self.read_header(previous_height)

        # Missing header, request it
        if not previous_header:
            return previous_height

        # Does it connect to my chain?
        prev_hash = self.hash_header(previous_header)
        if prev_hash != header.get('prev_block_hash'):
            self.print_error("reorg")
            return previous_height

        # The chain is complete.  Reverse to order by increasing height
        chain.reverse()
        if self.verify_chain(chain):
            self.print_error("connected at height:", previous_height)
            for header in chain:
                self.save_header(header)
            return True

        return False

    def connect_chunk(self, idx, chunk):
        try:
            self.verify_chunk(idx, chunk)
            return idx + 1
        except Exception:
            self.print_error('verify_chunk failed')
            return idx - 1
