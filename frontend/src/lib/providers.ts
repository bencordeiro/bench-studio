/** Chat Completions connection presets. Model IDs remain user-selected. */
export const PROVIDERS = [
  { id: "custom", name: "Custom / OpenAI-compatible", url: "", env: "", docs: "", hint: "Enter your server's API base URL and model ID." },
  { id: "ollama", name: "Ollama (local)", url: "http://127.0.0.1:11434/v1", env: "", docs: "https://docs.ollama.com/api/openai-compatibility", hint: "Use a model already installed in Ollama." },
  { id: "openai", name: "OpenAI", url: "https://api.openai.com/v1", env: "OPENAI_API_KEY", docs: "https://developers.openai.com/api/reference/overview", hint: "Choose a model that supports Chat Completions." },
  { id: "qwen", name: "Alibaba / Qwen (Singapore)", url: "https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1", env: "DASHSCOPE_API_KEY", docs: "https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope", hint: "Replace {WorkspaceId} with your Model Studio workspace ID. Match the URL region to your API key." },
  { id: "qwen-cn", name: "Alibaba / Qwen (Beijing)", url: "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1", env: "DASHSCOPE_API_KEY", docs: "https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope", hint: "Replace {WorkspaceId} with your Model Studio workspace ID. Use a Beijing-region API key." },
  { id: "deepseek", name: "DeepSeek", url: "https://api.deepseek.com/v1", env: "DEEPSEEK_API_KEY", docs: "https://api-docs.deepseek.com/", hint: "Enter the model ID from your DeepSeek account." },
  { id: "zai", name: "Z.ai", url: "https://api.z.ai/api/paas/v4", env: "ZAI_API_KEY", docs: "https://docs.z.ai/guides/overview/quick-start", hint: "General inference API. A coding subscription uses a separate endpoint; use your account's documented URL." },
  { id: "xai", name: "xAI", url: "https://api.x.ai/v1", env: "XAI_API_KEY", docs: "https://docs.x.ai/developers", hint: "Enter a Grok model ID supporting Chat Completions." },
  { id: "anthropic", name: "Anthropic / Claude", url: "https://api.anthropic.com/v1", env: "ANTHROPIC_API_KEY", docs: "https://platform.claude.com/docs/en/api/openai-sdk", hint: "Uses the Chat Completions compatibility API. Enter your Claude model ID; multi-workspace keys may require an anthropic-workspace-id custom header." },
  { id: "openrouter", name: "OpenRouter", url: "https://openrouter.ai/api/v1", env: "OPENROUTER_API_KEY", docs: "https://openrouter.ai/docs/api-reference/overview", hint: "Use the full provider/model ID from OpenRouter." },
  { id: "gemini", name: "Google Gemini", url: "https://generativelanguage.googleapis.com/v1beta/openai", env: "GEMINI_API_KEY", docs: "https://ai.google.dev/gemini-api/docs/openai", hint: "Uses Gemini's OpenAI-compatible API." },
  { id: "groq", name: "Groq", url: "https://api.groq.com/openai/v1", env: "GROQ_API_KEY", docs: "https://console.groq.com/docs/openai", hint: "Save, then use Models to discover available model IDs." },
  { id: "mistral", name: "Mistral", url: "https://api.mistral.ai/v1", env: "MISTRAL_API_KEY", docs: "https://docs.mistral.ai/api", hint: "Save, then use Models to discover available model IDs." },
];
