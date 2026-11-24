VARIANTS = {
    "0.6b-base": "clone",
    "1.7b-base": "clone",
    "0.6b-customvoice": "custom",
    "1.7b-customvoice": "custom",
    "1.7b-voicedesign": "design",
}
QUANTS = ("BF16", "Q8_0", "Q4_K_M")
MODEL_NAMES = {"base": "Base", "customvoice": "CustomVoice", "voicedesign": "VoiceDesign"}


def model_id(variant):
    size, family = variant.split("-", 1)
    return f"Qwen/Qwen3-TTS-12Hz-{size.upper()}-{MODEL_NAMES[family]}"


def filenames(variant, quant):
    return f"qwen-talker-{variant}-{quant}.gguf", f"qwen-tokenizer-12hz-{quant}.gguf"
