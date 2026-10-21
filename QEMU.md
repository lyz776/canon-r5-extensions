# QEMU-EOS：R5 离线环境

本阶段按机主要求先搭建模拟器。尚无 R5 ROM 转储，也没有运行原厂固件或连接相机。

## 固定来源与模型边界

- QEMU-EOS：[reticulatedpines/qemu-eos](https://github.com/reticulatedpines/qemu-eos/tree/4b667a1d3c08ab7a55835d15ddbd884fa754946d)，提交 `4b667a1d3c08ab7a55835d15ddbd884fa754946d`，来自 `qemu-eos-v4.2.1` 分支。默认 `master` 不是本次使用的 EOS 分支。
- [模型定义](https://github.com/reticulatedpines/qemu-eos/blob/4b667a1d3c08ab7a55835d15ddbd884fa754946d/hw/eos/model_list.c#L786)：R5 使用 DIGIC X 模型，两块 ROM 映射各为 64 MiB；RAM 大小仍标注为假设，启动标志处理有未解决注释。这是模拟器配置，不是本项目对真机容量的测量。
- [ROM 装载与启动](https://github.com/reticulatedpines/qemu-eos/blob/4b667a1d3c08ab7a55835d15ddbd884fa754946d/hw/eos/eos.c#L2011)：读取 `R5/ROM0.BIN`、`R5/ROM1.BIN`；DIGIC X 的起始 PC 被设为 `0xE0000000`，相关注释仍有 FIXME。Canon 的 `.FIR` 更新包不能直接当作完整 ROM 转储。
- [机身微控制器交互](https://github.com/reticulatedpines/qemu-eos/blob/4b667a1d3c08ab7a55835d15ddbd884fa754946d/hw/eos/mpu.c)：没有 R5 专用响应表，落到通用 `MPU spells`；不是肩屏、按钮或镜头交互的已验证实现。
- `eos.c` 中 DIGIC X 的部分外设使用 `DUMMYX` 处理。程序没有崩溃，不能证明真实外设行为正确；原厂基线研究必须记录经过的这些占位实现。

本次以 Windows/MSYS2 构建宿主端模拟器。ROM、卡镜像、编译器与构建产物保留在本地，不提交 GitHub。

## Windows 构建

使用独立 MSYS2 MINGW64 环境。本次基础环境为官方 MSYS2 2026-09-27，安装包 SHA-256 为 `ad336cccfda47758b5e15cda993fbba421115cb0b126697daef1ee4dfe37209f`。实际编译器 GCC 16.2.0，MSYS Python 3.12.15，GLib 2.90.1，pixman 0.46.4。

在 MINGW64 shell 中安装依赖：

```sh
pacman -S --needed make git diffutils flex bison python \
  mingw-w64-x86_64-gcc mingw-w64-x86_64-glib2 \
  mingw-w64-x86_64-pixman mingw-w64-x86_64-pkgconf
```

在同级目录准备 QEMU-EOS checkout。以下命令从本项目根目录运行；镜像只替换下载位置，子模块提交仍由上游固定。

```sh
git clone --branch qemu-eos-v4.2.1 https://github.com/reticulatedpines/qemu-eos.git ../qemu-eos
git -C ../qemu-eos checkout --detach 4b667a1d3c08ab7a55835d15ddbd884fa754946d
(
  cd ../qemu-eos
  git submodule init ui/keycodemapdb dtc tests/fp/berkeley-testfloat-3 tests/fp/berkeley-softfloat-3
  git config submodule.ui/keycodemapdb.url https://github.com/qemu/keycodemapdb.git
  git config submodule.dtc.url https://github.com/dgibson/dtc.git
  git config submodule.tests/fp/berkeley-testfloat-3.url https://github.com/qemu/berkeley-testfloat-3.git
  git config submodule.tests/fp/berkeley-softfloat-3.url https://github.com/qemu/berkeley-softfloat-3.git
  scripts/git-submodule.sh update ui/keycodemapdb dtc tests/fp/berkeley-testfloat-3 tests/fp/berkeley-softfloat-3
)
```

从本项目根目录运行（示例目录均需替换为实际 checkout）：

```sh
git -C ../qemu-eos apply "$PWD/qemu/windows-build.patch"
bash qemu/build_msys2.sh ../qemu-eos ../qemu-eos-build
```

构建脚本要求上游提交和差异恰好匹配已记录补丁。构建目录应与源码目录分开；MSYS2 在没有符号链接权限时会复制部分 Makefile，应用补丁应在首次配置之前完成。

若混用 Git for Windows 和 MSYS2 Git，需保持主仓库及子模块的 `core.autocrlf` 一致。本次 Windows checkout 使用 `true`；不同配置会把换行符误报为源码改动，构建脚本会拒绝继续。

累计补丁 `qemu/windows-build.patch` 包含宿主构建兼容修正及下述内存日志修复，遵循 QEMU 的 GPL-2.0-or-later 许可证；本仓库的 MIT 许可不替代 QEMU 许可。VNC 编译支持保留，但合成测试不会开启监听。此版本关闭了动态指令插件，不能直接套用依赖 `libmagiclantern.so` 的上游启动脚本；这不等于已验证所有上游调试功能。

补丁依据：

| 构建报错 | 最小修正 |
| --- | --- |
| MinGW 不接受 `-rdynamic` | Windows 构建不传该链接参数，其他平台保留 |
| 新版 GLib 的 Windows 头文件包含 C++ 模板，不能放在 `extern "C"` 中 | 将 `qemu/osdep.h` 移到该块外 |
| Windows 没有 POSIX `PROT_READ/PROT_WRITE` | 内存日志发送端和接收端统一使用 QEMU 自有 `PAGE_READ/PAGE_WRITE`；同步接口注释 |

日志修复把回调从旧包装移到共用的 32 位数据访问入口，并移除旧包装的回调，避免重复记录。读写完成后才调用日志；发生 MMU 异常则不会执行回调。同时修正 16 位值掩码 `0xFFFFF` 为 `0xFFFF`，移除写入完成后错误标为“旧值”的额外内存读取。

没有修改 R5 的内存映射、启动标志或外设占位返回值。构建仍有上游警告；编译成功不等于完成源码缺陷审计。

## 验证范围

合成测试只使用自写 ARM 指令、标记字符串和新建空白文件。它验证模型可以创建、指令可以执行、虚拟 RAM 可读写，以及错误/超时能否被宿主测试识别。

不验证：Canon 启动、官方更新包、机身 NVRAM、刷写/断电恢复、真实卡时序、肩屏、音频、传感器或视频吞吐。

合成程序仅在此测试中开启 semihosting，用于打印标记与返回退出状态。它不是相机启动入口。未来加载未知或真实固件时，不应沿用 semihosting；其主机文件访问能力不能被当作隔离机制。

测试为每次运行创建独立目录，ROM 与虚拟卡均为普通文件；没有物理磁盘、USB 转发、网络设备、VNC 或调试监听端口。QEMU 卡写入使用快照，运行后比较输入哈希。超时终止仅限测试启动的进程。宿主程序本身不能凭这些检查证明相机安全。

### 运行合成测试

使用 Python **3.11+**。基础测试只需已构建的 QEMU；完整日志回归还需要 GNU ARM binutils。本次使用 MSYS2 UCRT64 的 binutils 2.47，仅用于汇编自写测试。模拟器本身仍由 MINGW64 构建。

```sh
pacman -S --needed mingw-w64-ucrt-x86_64-arm-none-eabi-binutils
```

在 PowerShell 中从仓库根目录运行，替换实际路径：

```powershell
# 三项基础测试，不需要汇编器。
python -B qemu/smoke_r5.py "path/to/qemu-system-arm.exe" --work-dir ./local/qemu-smoke
# 完整日志回归。工具已在 PATH 时可省略 --binutils-prefix。
python -B qemu/smoke_r5.py "path/to/qemu-system-arm.exe" --work-dir ./local/qemu-smoke --probe-memory-log --binutils-prefix "C:/path/to/msys64/ucrt64/bin/arm-none-eabi-"
# 额外探测已知的上游对齐检查缺口；目前返回 1。
python -B qemu/smoke_r5.py "path/to/qemu-system-arm.exe" --work-dir ./local/qemu-smoke --probe-alignment --binutils-prefix "C:/path/to/msys64/ucrt64/bin/arm-none-eabi-"
```

自行构建时需让 QEMU 找到 MINGW64 DLL；交付目录已附运行库。binutils 使用自己的 UCRT64 运行库，勿用它们替换 QEMU 附带的 DLL。

测试生成普通临时文件，不使用 Canon ROM。`memory_log.S` 包含可审查的 ARM/Thumb 汇编；每次回归重新汇编，不提交二进制测试 ROM。`MODE=0/1/2` 分别选择 ARM、Thumb-16、Thumb-32 标量访问；`FAULT=1/2` 测试未映射页的读/写异常，`FAULT=3/4` 探测对齐异常。MMU 页表及地址仅属于合成测试。

### 日志修复验证（2026-10-21）

| 检查 | 结果 |
| --- | --- |
| 基础 ARM/RAM、故意错误退出、宿主死循环超时 | 3/3 通过 |
| 三种指令编码 × 关闭日志/只读/只写/读写 | 12/12 通过 |
| 三种编码 × MMU 未映射页读/写异常 | 6/6 通过；处理器报告预期异常和地址，失败访问没有完成记录 |
| 同一套 21 项回归运行于修复前二进制 | 6 通过、15 失败，证明测试可以检出原缺陷 |
| 额外 SCTLR.A 对齐异常探测 | 6/6 失败：开启对齐检查后非对齐访问仍完成，作为已知缺口保留 |

正常访问逐条核对 **地址、读写方向、值、宽度、顺序和次数**，包括 8/16/32 位访问、带符号半字、立即数/寄存器偏移、目标与基址重合以及 LDM/STM 多寄存器访问。测试程序还会自行比较加载值；只读/只写模式不得出现另一方向记录。检查的是完整测试轨迹，不能用一个成功字符串替代。

修复依据：[新解码路径](https://github.com/reticulatedpines/qemu-eos/blob/4b667a1d3c08ab7a55835d15ddbd884fa754946d/target/arm/translate.c#L8870)直接调用共用入口，却绕过了[旧包装中的日志回调](https://github.com/reticulatedpines/qemu-eos/blob/4b667a1d3c08ab7a55835d15ddbd884fa754946d/target/arm/translate.c#L1029)。本次在共用入口补齐回调，并移除旧包装调用；未另造第二套跟踪机制。

**剩余限制：** SCTLR.A 对齐检查尚不可靠；64 位、VFP/NEON、独占/原子指令、DMA、MMIO 和非恒等 MMU 映射不在本次验收范围，部分上游路径仍会漏记或触发断言。日志中的 PC 精度也未验证。不能将这次修复解释为全机内存访问已完整覆盖，或“日志里没有写入就一定安全”。

所有合成 ROM 和虚拟卡的运行前后 SHA-256 均保持一致；未测试虚拟卡写操作。超时只验证宿主终止测试进程，不代表相机看门狗或断电恢复。相机端没有执行任何代码，固件 2.0.0 的启动和恢复仍未验证。

## 下一阶段

机主已于 2026-10-21 报告固件版本为 2.0.0；版本信息本身不证明 QEMU 支持该固件。取得有合法来源且版本对应的 ROM 数据后，先运行未修改原厂基线，并记录首个不可执行/未建模点。不得因为模拟失败就直接跳过代码并记作通过，也不要求机主为了补齐输入而立即在真机上运行转储工具。
