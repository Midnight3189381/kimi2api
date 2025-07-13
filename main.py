import os
import time
import json
import httpx
import asyncio
import logging
from dotenv import load_dotenv
from typing import List, Dict, Optional, AsyncGenerator
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# --- 配置和初始化 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')
logger = logging.getLogger(__name__)
load_dotenv()
app = FastAPI(title="Kimi API Proxy", version="3.0.0-final")
KIMI_TOKENS_STR = os.getenv("KIMI_TOKENS")
if not KIMI_TOKENS_STR: raise ValueError("KIMI_TOKENS 环境变量未设置或为空")
KIMI_TOKENS = KIMI_TOKENS_STR.split(',')
token_index = 0
token_lock = asyncio.Lock()
conversation_storage: Dict[str, str] = {}
conversation_lock = asyncio.Lock()
KIMI_MODEL_MAPPING = {
    "k2":   {"model": "k2", "use_search": True},
    "k1.5": {"model": "k1.5", "use_search": True},
}

# --- Pydantic 模型定义 ---
class ModelCard(BaseModel): id: str; object: str = "model"; created: int = Field(default_factory=lambda: int(time.time())); owned_by: str = "kimi.ai"
class ModelList(BaseModel): object: str = "list"; data: List[ModelCard]
class Message(BaseModel): role: str; content: str
class ChatCompletionRequest(BaseModel): model: str; messages: List[Message]; stream: bool = False
class ChatCompletionResponseChoice(BaseModel): index: int; message: Message; finish_reason: Optional[str] = "stop"
class ChatCompletionResponse(BaseModel): id: str; object: str = "chat.completion"; created: int = Field(default_factory=lambda: int(time.time())); model: str; choices: List[ChatCompletionResponseChoice]; usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
class DeltaMessage(BaseModel): role: Optional[str] = None; content: Optional[str] = None
class ChatCompletionStreamResponseChoice(BaseModel): index: int; delta: DeltaMessage; finish_reason: Optional[str] = None
class ChatCompletionStreamResponse(BaseModel): id: str; object: str = "chat.completion.chunk"; created: int = Field(default_factory=lambda: int(time.time())); model: str; choices: List[ChatCompletionStreamResponseChoice]

# --- 核心辅助函数 ---
async def get_next_kimi_token() -> str:
    global token_index
    async with token_lock: token = KIMI_TOKENS[token_index]; token_index = (token_index + 1) % len(KIMI_TOKENS); return token
def get_common_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}","User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36","Content-Type": "application/json"}
async def create_kimi_chat_session(token: str) -> str:
    url = "https://www.kimi.com/api/chat"; headers = get_common_headers(token)
    payload = {"name": "未命名会话", "born_from": "home", "kimiplus_id": "kimi", "is_example": False, "source": "web", "tags": []}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=payload, timeout=20); response.raise_for_status()
            data = response.json(); chat_id = data.get("id")
            if not chat_id: raise ValueError(f"创建对话失败, 响应内容: {data}")
            return chat_id
        except Exception as e:
            logger.exception("创建 Kimi 对话时出错")
            if hasattr(e, 'response') and e.response is not None: logger.error(f"Kimi response body: {e.response.text}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create Kimi chat session.")

# --- 流式请求处理 ---
async def process_chat_request(request: ChatCompletionRequest, kimi_chat_id: str, kimi_token: str):
    model_config = KIMI_MODEL_MAPPING.get(request.model)
    if not model_config: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Model '{request.model}' not found.")
    user_message = next((msg.content for msg in reversed(request.messages) if msg.role == 'user'), None)
    if not user_message: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No user message found.")
    kimi_payload = {"model": model_config["model"], "use_search": model_config["use_search"], "messages": [{"role": "user", "content": user_message}], "kimiplus_id": "kimi", "extend": {"sidebar": True}, "refs": [], "history": [], "scene_labels": [], "use_semantic_memory": False, "use_deep_research": False}
    completion_url = f"https://www.kimi.com/api/chat/{kimi_chat_id}/completion/stream"
    headers = get_common_headers(kimi_token)

    async def stream_generator() -> AsyncGenerator[str, None]:
        buffer = ""
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("POST", completion_url, headers=headers, json=kimi_payload, timeout=180) as response:
                    response.raise_for_status()
                    async for raw_chunk in response.aiter_raw():
                        buffer += raw_chunk.decode('utf-8', 'ignore')
                        while '\n\n' in buffer:
                            message, buffer = buffer.split('\n\n', 1)
                            data_str = ""
                            for line in message.splitlines():
                                if line.startswith('data:'): data_str = line[len('data:'):].strip()
                            if not data_str: continue
                            if data_str == "[DONE]":
                                final_chunk = ChatCompletionStreamResponse(id=kimi_chat_id, model=request.model, choices=[ChatCompletionStreamResponseChoice(index=0, delta={}, finish_reason="stop")])
                                yield f"data: {final_chunk.model_dump_json()}\n\n"; yield "data: [DONE]\n\n"; return
                            try:
                                data_json = json.loads(data_str)
                                # --- 【最终极的核心修正】---
                                # 只处理事件类型为 "cmpl" (completion) 的消息
                                if data_json.get("event") == "cmpl":
                                    content = data_json.get("text", "")
                                    if content:
                                        chunk = ChatCompletionStreamResponse(id=kimi_chat_id, model=request.model, choices=[ChatCompletionStreamResponseChoice(index=0, delta=DeltaMessage(content=content))])
                                        yield f"data: {chunk.model_dump_json()}\n\n"
                            except json.JSONDecodeError: continue
        except Exception:
            logger.exception("流式生成器中出现未处理的异常")
            error_data = {"error": {"message": "An internal error occurred in the streaming proxy.", "type": "proxy_error"}}
            yield f"data: {json.dumps(error_data)}\n\n"; yield "data: [DONE]\n\n"

    if request.stream:
        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    else:
        full_content = ""; 
        try:
            async for chunk in stream_generator():
                if chunk.strip() == "data: [DONE]": break
                if chunk.startswith("data:"):
                    data_str = chunk[len("data:"):].strip();
                    if not data_str: continue
                    try:
                        data_json = json.loads(data_str)
                        if "error" in data_json: raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=data_json["error"]["message"])
                        delta = data_json.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content")
                        if content: full_content += content
                    except (json.JSONDecodeError, IndexError): continue
        except HTTPException as e: raise e
        choice = ChatCompletionResponseChoice(index=0, message=Message(role="assistant", content=full_content))
        return ChatCompletionResponse(id=kimi_chat_id, model=request.model, choices=[choice])

# --- API 端点 ---
@app.get("/v1/models", response_model=ModelList)
async def list_models(): return ModelList(data=[ModelCard(id=model_id) for model_id in KIMI_MODEL_MAPPING.keys()])
@app.post("/v1/chat/completions")
async def create_stateless_chat_completion(request: ChatCompletionRequest):
    kimi_token = await get_next_kimi_token(); kimi_chat_id = await create_kimi_chat_session(kimi_token)
    return await process_chat_request(request, kimi_chat_id, kimi_token)
@app.post("/v1/chat/completions/{conversation_id}")
async def create_stateful_chat_completion(conversation_id: str, request: ChatCompletionRequest):
    kimi_token = await get_next_kimi_token()
    async with conversation_lock:
        if conversation_id not in conversation_storage:
            kimi_chat_id = await create_kimi_chat_session(kimi_token)
            conversation_storage[conversation_id] = kimi_chat_id
        else: kimi_chat_id = conversation_storage[conversation_id]
    return await process_chat_request(request, kimi_chat_id, kimi_token)

# --- 运行服务器 ---
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Kimi API Proxy Server (Stable Version 3.0 - Final Fix)...")
    uvicorn.run(app, host="0.0.0.0", port=8000)