# Kimi Chat to OpenAI API 代理

[![Python](https://img.shields.io/badge/Python-3.8+-blue?logo=python)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green?logo=fastapi)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 将 Kimi Chat 的非官方 API 转换为标准的 OpenAI `v1/chat/completions` 接口，让你能够将 Kimi 的强大功能无缝对接到任何支持 OpenAI API 的第三方应用中。

这个项目诞生于一次细致的逆向工程和深入的调试过程，最终实现了对 Kimi Web 端 SSE (Server-Sent Events) 流的精确解析和转发。

## ⚠️ 免责声明

**本项目仅供学习和技术研究使用，旨在探索 Web API 的逆向工程和 SSE 流处理技术。**

*   本项目通过模拟 Web 客户端请求与 Kimi Chat 服务进行交互，并非由月之暗面（Moonshot AI）官方提供或认可。
*   项目作者不对任何因使用本项目而导致的直接或间接后果负责，包括但不限于账户限制、服务中断或数据丢失等。
*   请用户自觉遵守 Kimi Chat 的[用户服务协议](https://kimi.moonshot.cn/terms)。**我们强烈建议您在生产环境或商业用途中，使用月之暗面官方提供的正式 API 服务**，以获取稳定、合规的服务保障。
*   任何滥用本项目进行非法活动或违反 Kimi Chat 服务条款的行为，均由使用者自行承担全部责任。

**如果您下载、使用或分发本项目的代码，即代表您已阅读并同意此免责声明。**

## ✨ 功能特性

*   **OpenAI 格式兼容**: 完全兼容 `v1/chat/completions` 和 `v1/models` API，支持流式（`stream=true`）和非流式响应。
*   **多账户轮询**: 支持配置多个 Kimi Bearer Token，并以轮询方式使用，有效分摊请求压力，避免单一账户速率限制。
*   **默认联网搜索**: 对外提供的模型（`k2`, `k1.5`）默认开启 Kimi 的联网搜索功能，提供更具时效性的回答。
*   **有状态多轮对话**: 独创的 `/v1/chat/completions/{conversation_id}` 端点，可根据自定义会话 ID 维持服务端上下文，实现真正的多轮对话。
*   **部署简单**: 基于 FastAPI 构建，仅需一个 Python 文件和简单的配置即可运行。
*   **精确解析**: 完美处理 Kimi API 特有的 SSE 事件流（如 `cmpl` 事件），确保无“回音”、不丢消息。

## 🚀 快速开始

### 1. 先决条件

*   Python 3.8 或更高版本
*   `pip` 包管理器

### 2. 下载项目

使用 Git 克隆本仓库：
```bash
git clone <your-repo-url>
cd <your-repo-folder>
```
或者直接下载 `main.py` 文件。

### 3. 安装依赖

在项目根目录下，通过 pip 安装所有必需的库：
```bash
pip install "fastapi[all]" httpx python-dotenv
```

### 4. 配置密钥

这是最关键的一步。

1.  将项目中的 `.env.example` 文件（如果提供了）复制或重命名为 `.env`。如果不存在，请手动创建一个。
2.  编辑 `.env` 文件，内容如下：

    ```env
    # 将你的 Kimi Bearer Token 放在这里
    # 如果有多个，用英文逗号,隔开，不要有空格
    KIMI_TOKENS="token_1,token_2,token_3"
    ```

**如何获取 Bearer Token？**
1.  登录 [Kimi Chat 官网](https://kimi.moonshot.cn/)。
2.  打开浏览器开发者工具（通常是按 `F12`）。
3.  切换到 “网络 (Network)” 标签页。
4.  随便发送一条消息。
5.  在网络请求列表中，找到名为 `completion` 或 `stream` 的请求。
6.  点击该请求，在 “标头 (Headers)” 中找到 “请求标头 (Request Headers)”。
7.  复制 `authorization` 字段的完整值，它以 `Bearer ` 开头。将整个值粘贴到 `.env` 文件中。
8.  Token 有时效性，如果服务无法工作，请优先检查 Token 是否已过期。

### 5. 运行服务

在项目根目录下，运行以下命令启动 FastAPI 服务：
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```
现在，API 服务已在 `http://0.0.0.0:8000` 上运行。

## 📚 API 使用说明

### 模型列表

获取当前支持的模型。

*   **Endpoint**: `GET /v1/models`
*   **cURL 示例**:
    ```bash
    curl http://localhost:8000/v1/models
    ```
*   **预期输出**:
    ```json
    {
      "object": "list",
      "data": [
        { "id": "k2", "object": "model", "owned_by": "kimi.ai", ... },
        { "id": "k1.5", "object": "model", "owned_by": "kimi.ai", ... }
      ]
    }
    ```

### 无状态（单轮）聊天

每次请求都是一个全新的对话，不记忆之前的上下文。

*   **Endpoint**: `POST /v1/chat/completions`
*   **cURL 示例 (流式)**:
    ```bash
    curl http://localhost:8000/v1/chat/completions \
      -H "Content-Type: application/json" \
      -d '{
        "model": "k2",
        "messages": [{"role": "user", "content": "你好，请介绍一下 Python 语言。"}],
        "stream": true
      }'
    ```

### 有状态（多轮）聊天

通过在 URL 中提供一个自定义的 `conversation_id` 来维持对话上下文。

*   **Endpoint**: `POST /v1/chat/completions/{conversation_id}`

*   **cURL 示例**:

    **第一轮:**
    ```bash
    # 使用 "my-unique-chat-123" 作为会话 ID
    curl http://localhost:8000/v1/chat/completions/my-unique-chat-123 \
      -H "Content-Type: application/json" \
      -d '{
        "model": "k2",
        "messages": [{"role": "user", "content": "请推荐一部关于太空探索的科幻电影。"}],
        "stream": false
      }'
    ```
    *(假设模型推荐了《星际穿越》)*

    **第二轮:**
    ```bash
    # 继续使用同一个会话 ID
    curl http://localhost:8000/v1/chat/completions/my-unique-chat-123 \
      -H "Content-Type: application/json" \
      -d '{
        "model": "k2",
        "messages": [{"role": "user", "content": "这部电影的导演是谁？"}],
        "stream": false
      }'
    ```
    *(模型会理解“这部电影”指的是《星际穿越》，并给出正确回答)*

## 🧩 对接第三方应用

你可以将此服务接入任何支持 OpenAI API 的客户端，如 [NextChat](https://github.com/Yidadaa/ChatGPT-Next-Web), [LobeChat](https://github.com/lobehub/lobe-chat), [Amo.ai](https://github.com/AmoAloha/Amo-Ai-Chat) 等。

在客户端设置中，请填写：
*   **API 地址 (Endpoint)**: `http://<你的服务器IP>:8000/v1`
*   **API 密钥 (API Key)**: 可以任意填写，例如 `sk-kimi`。
*   **模型 (Model)**: 选择 `k2` 或 `k1.5`。

## 📝 注意事项

*   多轮对话的会话状态是存储在服务内存中的，如果服务重启，所有会话历史都将丢失。
*   请遵守 Kimi 的使用条款。频繁的请求可能会导致你的账户或 IP 被临时限制。
*   Kimi 的 Bearer Token 具有时效性，如果 API 返回错误，请首先检查 Token 是否已过期。
