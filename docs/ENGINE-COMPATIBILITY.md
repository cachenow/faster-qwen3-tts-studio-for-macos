# GGML 兼容性

faster-qwen3-tts 0.5.4，审阅源码 commit `b35fdc7d71eb3e4d19e63f4b4a330a1aef31d682`。qwentts-cpp-python 0.5.0，审阅源码 commit `6f756c4fe99e3afe722cfebd0c7085b8e38b70e0`，实际打包以 PyPI wheel 为准。PyPI 提供 `py3-none-macosx_14_0_arm64` ABI v5 wheel，SHA-256 为 `04546453b573afc5f0fbc8ba3c8fc810fef6367c4b603b9b5a1ef0dd459ed1a9`。

运行时发布工作流指定 qwentts.cpp `6fae92914045cd83364d2845ceaa0f7969727319`，其 GGML submodule 为 `40e16e4a814f7fe851a0c486fb9e8c722e957830`。检查了设备选择源码，指定设备初始化失败会报错。

| 模型 | GGUF 文件存在 | 接口 | 硬件状态 |
| --- | --- | --- | --- |
| 0.6B Base | BF16、Q8_0、Q4_K_M | ICL、X-vector | Pending Hardware Validation |
| 1.7B Base | BF16、Q8_0、Q4_K_M | ICL、X-vector | Pending Hardware Validation |
| 0.6B CustomVoice | BF16、Q8_0、Q4_K_M | 预设音色 | Pending Hardware Validation |
| 1.7B CustomVoice | BF16、Q8_0、Q4_K_M | 预设音色 | Pending Hardware Validation |
| 1.7B VoiceDesign | BF16、Q8_0、Q4_K_M | 自然语言描述 | Pending Hardware Validation |

匹配相同量化等级的 Talker 与 12Hz Codec。模型下载指向同一 GGUF 仓库修订。按 Hugging Face 提供的 LFS SHA-256 和长度校验，验证后才注册文件。推理强制 `GGML_BACKEND=MTL0`，传入两个本地路径。Base 模型拒绝 instruct。语言由上游处理，应用提供 Auto。推理工作进程退出后释放模型，每次任务独立加载，长文本分段复用单任务内加载的模型。

上游会按重采样后的音频内容、模型标识和 native 版本缓存 `.spk` 和 `.rvq`。Studio 再按推理依赖版本、模型、量化和参考文本分隔目录。后端接收 PCM WAV，前端可将浏览器能够解码的参考音频转成 PCM。WKWebView 的 MP3、FLAC 和 M4A 兼容性待验证。

- [GGML API](https://github.com/andimarafioti/faster-qwen3-tts/blob/b35fdc7d71eb3e4d19e63f4b4a330a1aef31d682/docs/ggml-backend.md)
- [GGUF 目录](https://huggingface.co/Serveurperso/Qwen3-TTS-GGUF/tree/b7ee2e8)
- [Metal wheel](https://pypi.org/project/qwentts-cpp-python/0.5.0/#files)
