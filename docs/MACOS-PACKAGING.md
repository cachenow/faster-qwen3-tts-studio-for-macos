# macOS ARM64 打包

构建使用 GitHub 的 macos-15 ARM64 runner 和目标 aarch64-apple-darwin。macOS 14.0 部署目标通过 Bundle 配置及逐 Mach-O 检查约束。

`bash scripts/build/macos.sh` 使用固定版本的构建工具与独立 ARM64 Python 3.12.12。Metal wheel 从锁文件安装。脚本检查运行时、原生库、目标架构、依赖引用与最低系统版本。引用构建机器路径时，如果 Bundle 内有唯一同名库，脚本将其改写为相对于加载方的位置。含糊或缺失的引用会阻止打包。

采用本机免费 Ad-hoc 签名。先签原生文件，再签外层 App。预览构建不启用 Hardened Runtime，也不配置 Library Validation 相关放开权限。DMG 构建后挂载，验证签名并执行桌面启动和后端健康测试。App ZIP 使用 ditto 保存权限及符号链接。

macOS CI 环境负责验证构建和启动。Metal、WKWebView 音频、麦克风许可、普通用户通过“仍要打开”启动等由真实 Apple Silicon 机器验证。
