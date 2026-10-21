# R5 一代：依据与首次交付风险记录

调查日期：2026-10-21。用户机身的准确固件版本未知。以下“源码已确认”表示在指定提交中读到了相应实现或注释，不表示已经在我们的 R5 上复现。

## 已检查的 Magic Lantern 基线

仓库：[reticulatedpines/magiclantern_simplified](https://github.com/reticulatedpines/magiclantern_simplified)。固定提交：`142472e95054d73640f50789ac0fd66325499d82`，上游提交日期 2026-10-04。我们只读取了源码，没有修改、编译或发布上游二进制。

1. **现有平台目录是 R5.152。** [Makefile](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/platform/R5.152/Makefile#L1) 明确给出 `FW_VERSION = 152`；[stubs.S](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/platform/R5.152/stubs.S#L1) 标明地址来自 R5 1.5.2。这些地址不能平移到未知版本。
2. **有平台支持不等于具有三个目标功能。** [features.h](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/platform/R5.152/features.h#L1) 主要启用 RGBA 合成、任务/CPU/GUI 等调试功能，并禁用属性写入、崩溃日志和自动 ROM 备份。[function_overrides.c](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/platform/R5.152/function_overrides.c#L137) 将一批 EDMAC/寄存器接口实现为占位空函数，注释直接标为临时错误实现。因此不能把这些名字的存在当作视频处理路径已经可用。
3. **有明确的崩溃记录。** [internals.h](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/platform/R5.152/internals.h#L11) 说明 SRM 分配即使只请求一个缓冲区也会崩溃。[stubs.S](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/platform/R5.152/stubs.S#L163) 解释 DIGIC X 的相关旧入口为触发断言的占位函数。
4. **上游自身限制属性写入。** [property_whitelist.h](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/platform/R5.152/property_whitelist.h#L5) 提醒错误的属性写入可能导致变砖，写入白名单为空；部分属性连订阅处理器都被禁用。读取或订阅相机内部状态也不应笼统视作无副作用。
5. **平台编译目标与安装器需要分别判断。** [platform/Makefile](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/platform/Makefile#L71) 的默认列表包含 R5.152；[installer/Makefile](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/installer/Makefile#L54) 的默认列表没有 R5，所检查的 installer 目录也没有 R5 专用子目录。通用安装器中有 DIGIC X 条件分支，这仍不能证明已有适配当前机身版本的可用安装器。

## 启动、识别与恢复的限制

[src/reboot.c](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/src/reboot.c#L263) 在启动时检查一段内存的校验值；[fw-signature.h](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/src/fw-signature.h#L5) 给出了 R5 1.5.2 的值和逐个 32 位字累加算法。它不是 Canon 公钥数字签名，也不是整个 FIR 的 SHA-256，不能用来证明官方来源或完整固件兼容性。校验失败会进入停止路径，不等于已验证能正常恢复开机。

[src/boot-d678.c](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/src/boot-d678.c#L118) 记录 DIGIC X 加载 `autoexec.bin` 时会清除一段与 CamIF 协处理器共享的内存，因而需要在正确阶段重新初始化。这是上游对已观察行为的描述；不是本项目的实测结果。[internals-common.h](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/src/internals-common.h#L49) 为 DIGIC X 启用相应修复。**仅仅“从卡运行”或“只改 RAM”并不足以推导启动安全。**

[src/installer.c](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/src/installer.c#L64) 的通用代码注释警告：在错误的运行状态调用启动标志操作，可能中途失败并留下擦除的启动标志区域。这段警告不能当作 R5 故障的实测，但足以否定“拔卡一定恢复”的通用保证。

[src/bootflags.c](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/src/bootflags.c#L108) 还会直接写卡的引导扇区；所检查的设备选择分支没有 R5 专门处理，而 R5 的 [sd_device 声明](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/platform/R5.152/stubs.S#L170) 仍是零地址占位。不能将通用代码直接用于这台相机。

对未知版本，当前没有已验证的代码执行入口、备份还原方案、启动标志回退方案或断电恢复方案。未进行降级，也未要求机主运行任何机内程序。

## 三项功能的最小调查方向

### 肩屏曝光倒计时

Canon [R5 B 门说明](https://cam.start.canon/hy/C003/manual/html/UG-02_ShootingMode_0090.html) 说明：肩屏显示曝光经过时间，内置 B 门计时器可以设定时长。[规格](https://cam.start.canon/hy/C003/manual/html/UG-09_Reference_0100.html) 将肩屏列为 128×128 点阵反射式记忆液晶。这证明已有计时与显示功能，不证明任意内容绘制接口已公开，也不证明当前显示的就是剩余时间。

最小候选方向是找到“设定时长、实际曝光起止、肩屏时间字段”三者的现有路径，只研究时间字段的呈现。不能假设后屏 RGBA 接口可以控制肩屏。只有取得对应固件证据后才决定补丁位置；现在不先造一个模拟驱动。

未来验收应包含提前终止、曝光结束、取消、休眠/唤醒，以及曝光后的长曝光降噪状态，避免把降噪或预设时长误当作曝光仍在进行；还需验证普通定时曝光与 B 门是否共用路径。

### 自定义电子快门声音

ML [src/beep.c](https://github.com/reticulatedpines/magiclantern_simplified/blob/142472e95054d73640f50789ac0fd66325499d82/src/beep.c#L45) 有 WAV/提示音逻辑，但明确避开录音和某些视频 LiveView 状态，并包含等待播放完成的循环。检查的 R5 `stubs.S` 中没有定位到这些通用播放函数的可用 R5 对应入口。因此尚未证明能复用 ML 的音频功能。

需要先确认曝光事件、扬声器播放通路、任务上下文和录音互斥关系。若可实现，候选设计应为有界、非阻塞的通知；忙时丢弃提示音不能拖慢快门，也不能向录音流程抢资源。声音与电子快门扫描不可能仅凭一个按键事件就保证同步，连拍行为也必须另行定义和验证。

### 4K 50/60p 超采样

Canon [R5 规格](https://cam.start.canon/hy/C003/manual/html/UG-09_Reference_0100.html) 列出 8K 最高 29.97/25p，4K HQ/Fine 的高质量路径最高约 30p，普通 4K 可到 59.94/50p。[Canon 超采样介绍](https://www.canon-europe.com/pro/stories/filming-8k-4k-oversampled/) 可用于确认处理目标。

按同一 DCI 栅格作数量级估算：8192×4320×30 约为 10.6 亿个输入像素/秒；以 60p 全尺寸采样则约为 21.2 亿个输入像素/秒。输出为 4K 并不让输入采样减半；这些数字也不是已测得的 R5 芯片吞吐量。RAW 输出和实时去马赛克、降采样、处理、编码走的工作量不同。

Canon [R5 与 R5 C 比较](https://www.canon-europe.com/pro/stories/eos-r5-c-vs-eos-r5/) 说明两者使用相同的 45MP 传感器，而 R5 C 可提供 8K60。它支持“继续调查传感器能力”，但不能证明 R5 在自身电源、板级配置、散热、ISP 和内存条件下也能完成同一模式。

目前既不宣布硬件绝对做不到，也不宣布只是软件锁。需要逐段核对读出模式、时钟/吞吐、缓冲区、处理及编码限制。不能仅改菜单或帧率标签充当实现，不能先关闭温度/电源保护来尝试。

未来验收必须证明每秒确有 50/60 个独立的高分辨率采样结果，且输出经过目标超采样：检查实际读出尺寸、视角、细节/混叠、重复帧/丢帧、持续录制、音画同步，以及温度与功耗行为。分辨率元数据或播放器显示“60 fps”本身不构成证据。

## 首次交付的自测与变砖评估

本次只交付原创电脑端 Python 工具、测试和记录；没有相机端构建产物。工具没有网络、USB/PTP、固件修改、启动标志、NVRAM、传感器或时钟寄存器操作。GitHub 创建/推送是开发环境操作，不是工具功能。

| 风险机制 | 本次处理及实际验证 |
| --- | --- |
| 用错机型/版本仍被放行 | 不根据文件名、字符串或匹配哈希判断兼容性；测试始终得到 `unverified` 与 `safe_to_flash: false` |
| 输入读取不完整却输出成功 | 合成测试覆盖读取故障、截断、追加、同长度改写；错误时不输出部分指纹 |
| 工具覆盖研究文件 | 只读打开；跨块测试确认字节与修改时间保留；不提供写文件选项。用户自行使用 shell 重定向仍需指定不同文件 |
| 引导扇区/启动标志/NVRAM 破坏 | 本次没有相应写入路径；未来相机代码的恢复性尚未建立 |
| 错误地址、内存/协处理器破坏、音频资源冲突、过热 | 本次没有相机执行代码；尚未做相关真机实验，不能从电脑测试推断机内安全 |

自测命令：`python -B -m unittest discover -s tests -v`。Windows / Python 3.12.14，12 项测试通过；所有样本均为临时合成数据。检查了命令行退出码、JSON 的不可放行语义、中文路径和输入保留。初次测试暴露本环境 `stat` 与 `fstat` 对 `ctime` 的含义差异，已缩减为比较文件标识、大小及修改时间；不声称具备抵御恶意并发篡改的能力。

本次没有进行 Canon 固件真实性/签名验证、R5 仿真启动、ARM 构建或真机测试。普通文件的指纹计算成功不能替代这些工作，也不能给出未来补丁的变砖概率。

## 下一阶段所需的实际输入

先确认相机菜单显示的完整固件版本，以及用于分析的对应 Canon 官方文件来源；不需要机身序列号。用本工具固定文件字节身份后，再验证该版本的格式与映射。除非获得足够证据，否则保持未知地址、未知属性和未知恢复路径不进入真机实验。该条件是针对具体缺失事实的技术边界，不是要求再次授权整个工程。
