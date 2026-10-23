# canon-r5-extensions

佳能 EOS R5 一代的离线固件研究仓库，提供只读文件指纹工具、QEMU-EOS 构建补丁和可操作演示。非 Canon 或 Magic Lantern 官方项目，不提供相机安装包。

## 使用

安装 Python 3.11+，在仓库目录中运行。计算电脑上文件的大小和 SHA-256：

```sh
python -B inspect_firmware.py "path/to/firmware.FIR"
```

按 [QEMU 构建说明](QEMU.md)准备模拟器，启动可单步、断点、暂停的窗口：

```sh
python -B qemu/demo.py "path/to/qemu-system-arm.exe"
```

操作与验收见 [DEMO.md](DEMO.md)，构建和合成回归见 [QEMU.md](QEMU.md)，源码调查见 [RESEARCH.md](RESEARCH.md)。

## 风险提示

- 文件哈希不验证机型、固件兼容性或签名，也不代表可以刷写。
- QEMU 的 R5 模型和内存日志存在缺口；合成测试通过不能证明原厂固件可启动，或真机补丁不会变砖。
- 工具仅供电脑端使用，不要将合成测试数据用于相机。固件转储和机身数据不要提交到公开仓库。
