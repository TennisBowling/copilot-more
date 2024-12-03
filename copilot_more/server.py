from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from aiohttp import ClientSession, ClientTimeout
import json

from copilot_more.token import get_cached_copilot_token
from copilot_more.logger import logger

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


API_URL = "https://api.individual.githubcopilot.com/chat/completions"
TIMEOUT = ClientTimeout(total=300)

def preprocess_request_body(request_body: dict) -> dict:
    """
    Preprocess the request body to handle array content in messages.
    """
    if not request_body.get("messages"):
        return request_body

    processed_messages = []

    for message in request_body["messages"]:
        if not isinstance(message.get("content"), list):
            processed_messages.append(message)
            continue

        for content_item in message["content"]:
            if content_item.get("type") != "text":
                raise HTTPException(400, "Only text type is supported in content array")

            processed_messages.append({
                "role": message["role"],
                "content": content_item["text"]
            })

    return {
        **request_body,
        "messages": processed_messages
    }

@app.post("/chat/completions")
async def proxy_chat_completions(request: Request):
    """
    Proxies chat completion requests with SSE support.
    """

    
    request_body = await request.json()
    original_model = request_body['model']

    if original_model == "gemma-7b-it":
        request_body["model"] = "claude-3.5-sonnet"
    else if original_model == "llama3-70b-8192":
        request_body["model"] = "o1-preview"
    else if original_model == "llama3-8b-8192":
        request_body["model"] = "gpt-4o"
    else if original_model == "mixtral-8x7b-32768":
        request_body["model"] = "o1-mini"
    print(f"original {original_model} to {request_body['model']}")

    logger.info(f"Received request: {json.dumps(request_body, indent=2)}")

    try:
        request_body = preprocess_request_body(request_body)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(400, f"Error preprocessing request: {str(e)}")

    async def stream_response():
        try:
            token = await get_cached_copilot_token()
            async with ClientSession(timeout=TIMEOUT) as session:
                async with session.post(
                    API_URL,
                    json=request_body,
                    headers={
                        "Authorization": f"Bearer {token['token']}",
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                        "editor-version": "vscode/1.95.3"
                    },
                ) as response:
                    if response.status != 200:
                        error_message = await response.text()
                        logger.error(f"API error: {error_message}")
                        raise HTTPException(
                            response.status,
                            f"API error: {error_message}"
                        )

                    async for chunk in response.content.iter_chunks():
                        if chunk:
                            yield chunk[0]

        except Exception as e:
            logger.error(f"Error in stream_response: {str(e)}")
            yield json.dumps({"error": str(e)}).encode("utf-8")

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
    )
