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

Windows 补丁遵循 QEMU 的 GPL-2.0-or-later 许可证，属于上游宿主构建兼容修正；本仓库的 MIT 许可不替代 QEMU 许可。VNC 编译支持保留，但合成测试不会开启监听。此版本关闭了动态指令插件，不能直接套用依赖 `libmagiclantern.so` 的上游启动脚本；这不等于已验证所有上游调试功能。

补丁依据：

| 构建报错 | 最小修正 |
| --- | --- |
| MinGW 不接受 `-rdynamic` | Windows 构建不传该链接参数，其他平台保留 |
| 新版 GLib 的 Windows 头文件包含 C++ 模板，不能放在 `extern "C"` 中 | 将 `qemu/osdep.h` 移到该块外 |
| Windows 没有 POSIX `PROT_READ/PROT_WRITE` | 内存日志发送端和接收端统一使用 QEMU 自有 `PAGE_READ/PAGE_WRITE`；同步接口注释 |

没有修改 R5 的内存映射、启动标志、外设占位返回值或指令执行结果。构建仍有上游警告；编译成功不等于完成源码缺陷审计。

## 验证范围

合成测试只使用自写 ARM 指令、标记字符串和新建空白文件。它验证模型可以创建、指令可以执行、虚拟 RAM 可读写，以及错误/超时能否被宿主测试识别。

不验证：Canon 启动、官方更新包、机身 NVRAM、刷写/断电恢复、真实卡时序、肩屏、音频、传感器或视频吞吐。

合成程序仅在此测试中开启 semihosting，用于打印标记与返回退出状态。它不是相机启动入口。未来加载未知或真实固件时，不应沿用 semihosting；其主机文件访问能力不能被当作隔离机制。

测试为每次运行创建独立目录，ROM 与虚拟卡均为普通文件；没有物理磁盘、USB 转发、网络设备、VNC 或调试监听端口。QEMU 卡写入使用快照，运行后比较输入哈希。超时终止仅限测试启动的进程。宿主程序本身不能凭这些检查证明相机安全。

### 运行合成测试

使用 Python **3.11+**（本次为 3.12.14）。在 Windows PowerShell 中运行；自行构建时，先将 MSYS2 的 `mingw64/bin` 加入当前进程的 PATH，以找到 DLL。交付目录已附所需 DLL，无需该步骤。

```powershell
python -B qemu/smoke_r5.py ../qemu-eos-build/arm-softmmu/qemu-system-arm.exe --work-dir ../qemu-smoke
# 额外检查 RAM 日志完整性；本次固定版本的这项检查失败，退出码为 1。
python -B qemu/smoke_r5.py ../qemu-eos-build/arm-softmmu/qemu-system-arm.exe --work-dir ../qemu-smoke --probe-memory-log
```

默认运行三项基础测试，全部通过才返回 0；任何检查失败返回 1。可选日志检查也执行严格断言，没有将已知失败当作通过。临时文件自动清理，不生成供相机使用的安装文件。

### 本次结果（2026-10-21）

Windows 可执行程序报告 QEMU 4.2.1，`-machine help` 列出 `R5 / Canon EOS R5`。合成测试结果：

| 检查 | 实际结果 |
| --- | --- |
| ARM 指令及 RAM 存取，打印完成标记并退出 | 通过，退出 0 |
| 故意比较错误值 | 通过，正确观察到退出 1，且无完成标记 |
| 打印标记后死循环 | 通过，宿主在 5 秒上限后终止子进程；不代表模拟了相机看门狗 |
| ROM 与虚拟卡输入字节不变 | 所有用例前后 SHA-256 一致；未测试虚拟卡写操作 |
| `-d ramr` / `-d ramw` 输出测试地址访问记录 | **两项均失败**，不能依赖这些日志判断没有越界或没有写入 |

日志缺口有源码依据：[新解码路径](https://github.com/reticulatedpines/qemu-eos/blob/4b667a1d3c08ab7a55835d15ddbd884fa754946d/target/arm/translate.c#L8870)直接调用 `gen_aa32_ld_i32/st_i32`，没有经过[附带回调的旧包装](https://github.com/reticulatedpines/qemu-eos/blob/4b667a1d3c08ab7a55835d15ddbd884fa754946d/target/arm/translate.c#L1029)。本次没有扩展修改指令翻译器来修复它。日志模式初始化成功只能说明选项被识别，不能证明逐次访问已被记录。

原有只读文件指纹工具的 12 项单元测试也通过。未运行上游全套相机固件回归测试，因为没有所需 ROM 输入。本交付不是完整的 R5 虚拟机，更不是防变砖认证环境。

交付构建脚本已在现有构建目录完整运行成功；补丁在固定上游原文件副本上通过应用检查，并逐文件复现五处文件差异。脚本也正确拒绝了错误的源码提交。Windows 交付程序附带所需 DLL，在 PATH 仅含系统目录且 EOS 继承路径被故意设错的环境下，重新得到上述基础通过、日志失败的结果。

## 下一阶段

取得准确固件版本以及有合法来源的相应 ROM 数据后，先运行未修改原厂基线，并记录首个不可执行/未建模点。不得因为模拟失败就直接跳过代码并记作通过，也不要求机主为了补齐输入而立即在真机上运行转储工具。
