# Copyright 2026 K3 vs Raspberry Pi 5 Benchmark Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Linux port for Clang with the upstream SpacemiT X100 scheduling model.
include posix/core_portme.mak

X100_ARCH = rv64imafdcbv_zic64b_zicbom_zicbop_zicboz_ziccamoa_ziccif_zicclsm_ziccrse_zicntr_zicond_zicsr_zifencei_zihintntl_zihintpause_zihpm_zimop_zmmul_za64rs_zaamo_zalrsc_zawrs_zfa_zfhmin_zca_zcb_zcd_zcmop_zba_zbb_zbc_zbs_zkt_zvbb_zve32f_zve32x_zve64d_zve64f_zve64x_zvfhmin_zvkb_zvkt_zvl128b_zvl256b_zvl32b_zvl64b_supm

# Scalar code generation is deliberate. Vectorized CoreMark loops are slower
# on current X100 implementations, while the compiler scheduling model still
# applies to the scalar list, state, and matrix kernels.
PORT_CFLAGS = -O3 -fno-vectorize -fno-slp-vectorize \
	-march=$(X100_ARCH) -mabi=lp64d -mtune=spacemit-x100

# Keep the selected port file in the dependency graph inherited from posix.
EXTRA_DEPENDS += $(PORT_DIR)/core_portme.mak
