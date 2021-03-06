"""
Copyright 2019 FireEye, Inc.

Author: Omar Sardar <omar.sardar@fireeye.com>
Name: SmkmStore.py

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import logging
import struct

from Tools import Tools


class SmkmStore(Tools):
    """
    The SmkmStore class corresponds to the Windows 10 SMKM_STORE structure.
    Each SMKM_STORE structure represents a single store. The information in this
    structure, and nested structures, is used to locate the specific region containing the
    compressed page.
    """
    def __init__(self, loglevel=logging.INFO):
        self.tools = super(SmkmStore, self).__init__()
        self.logger = logging.getLogger("SMKM_STORE")
        self.logger.setLevel(loglevel)
        self.fe = self.get_flare_emu()
        return

    def _dump(self):
        """
         Architecture agnostic function used to dump all located fields.
         """
        arch = 'x64' if self.Info.is_64bit() else 'x86'
        self.logger.info("StStore: {0:#x}".format(self.Info.arch_fns[arch]['sks_ststore'](self)))
        self.logger.info("pCompressedRegionPtrArray: {0:#x}".format(self.Info.arch_fns[arch]['sks_compressedregionptrarray'](self)))
        self.logger.info("StoreOwnerProcess: {0:#x}".format(self.Info.arch_fns[arch]['sks_storeownerprocess'](self)))
        return

    def _dump64(self):
        return

    @Tools.Info.arch32
    @Tools.Info.arch64
    def sks_ststore(self):
        """
        This nested structure contains another nested structure (ST_DATA_MGR), typically at a
        non-zero offset. See ST_DATA_MGR for additional information. Function should be updated
        if this changes in the future.
        """
        # Assumption is that the ST_STORE struct is nested @ offset 0
        return 0

    @Tools.Info.arch32
    @Tools.Info.arch64
    def sks_compressedregionptrarray(self):
        """
        This field is a pointer to an array of pointers in the MemCompression.exe process. An index
        into this array is indirectly derived from the SM_PAGE_KEY. This function loads the SMKM_STORE
        structure with a pre-defined pattern. The SmStMapVirtualRegion function is traversed while
        a memory hook monitors for read events. This signature is fragile in that we're relying on the
        first memory read of the function to be the field of interest. Disassembly snippet from
        Windows 10 1809 x86 shown below.

        SmStMapVirtualRegion      ?SmStMapVirtualRegion@?$SMKM_STORE@USM_TRAITS...
        SmStMapVirtualRegion                      mov     edi, edi
        SmStMapVirtualRegion+2                    push    ebp
        SmStMapVirtualRegion+3                    mov     ebp, esp
        SmStMapVirtualRegion+5                    and     esp, 0FFFFFFF8h
        SmStMapVirtualRegion+8                    sub     esp, 34h
        SmStMapVirtualRegion+B                    push    ebx
        SmStMapVirtualRegion+C                    push    esi
        SmStMapVirtualRegion+D                    push    edi
        SmStMapVirtualRegion+E                    mov     edi, ecx
        SmStMapVirtualRegion+10                   mov     [esp+40h+var_28], edx
        SmStMapVirtualRegion+14                   mov     [esp+40h+var_1C], edi
        SmStMapVirtualRegion+18                   mov     eax, [edi+1184h]
        """
        (fn_addr, fn_name) = self.find_ida_name("SmStMapVirtualRegion")
        pat = self.patgen(8192)
        lp_smkmstore = self.fe.loadBytes(pat)
        reg_cx = 'rcx' if self.Info.is_64bit() else 'ecx'
        mHookData = {'offset': None, 'structAddr': lp_smkmstore}

        def mHook(uc, accessType, memAccessAddress, memAccessSize, memValue, userData):
            if mHookData['offset']:
                return

            if accessType == 16: # UC_MEM_READ
                self.logger.debug("Mem read @ 0x{0:x}: {1}".format(memAccessAddress, memValue))
                mHookData['offset'] = memAccessAddress

        regState = {reg_cx: lp_smkmstore}
        self.fe.emulateRange(fn_addr, registers=regState, memAccessHook=mHook)
        return mHookData['offset'] - mHookData['structAddr']

    @Tools.Info.arch32
    @Tools.Info.arch64
    def sks_storeownerprocess(self):
        """
        This field contains a pointer to the process being used as a container for compressed memory. As
        of Windows 10 1607, this field has pointed to MemCompression.exe. The first argument to KiStackAttachProcess
        is the process to which the current kernel thread will attach to. This is the address of the store
        owner process in the case of Win10 memory decompression. Disassembly snippet from Windows 10 1809 x86
        shown below.

        SmStDirectRead+35                   mov     ecx, [ebx+1254h] ; BugCheckParameter1
        SmStDirectRead+3B                   lea     eax, [ebp+var_1C]
        SmStDirectRead+3E                   push    eax             ; int
        SmStDirectRead+3F                   xor     edx, edx
        SmStDirectRead+41                   call    _KiStackAttachProcess@12 ; KiStackAttachProcess(x,x,x)
        """
        (startAddr, endAddr) = self.locate_call_in_fn("?SmStDirectRead@?$SMKM_STORE", "KiStackAttachProcess")
        pat = self.patgen(8192)
        addr_smkmstore = self.fe.loadBytes(pat)
        reg_cx = 'rcx' if self.Info.is_64bit() else 'ecx'
        struct_fmt = "<Q" if self.Info.is_64bit() else "<I"

        def pHook(self, userData, funcStart):
            self.logger.debug("pre emulation hook loading ECX")
            userData["EmuHelper"].uc.reg_write(userData["EmuHelper"].regs["cx"], addr_smkmstore)

        self.fe.iterate([endAddr], self.tHook, preEmuCallback=pHook)
        reg_ecx = self.fe.getRegVal(reg_cx)
        return pat.find(struct.pack(struct_fmt, reg_ecx))
