import os
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("agentos.cognition.llm")

class LLMResponse:
    def __init__(self, content: Optional[str], tool_calls: Optional[List[Dict[str, Any]]] = None):
        self.content = content
        self.tool_calls = tool_calls or []

class LLMGateway:
    def __init__(self):
        self.openai_client = None
        self.anthropic_client = None
        self.gemini_client = None
        self.mistral_api_key = None
        self._init_clients()
        
    def _init_clients(self):
        # OpenAI
        if os.environ.get("OPENAI_API_KEY"):
            try:
                from openai import OpenAI
                self.openai_client = OpenAI()
            except ImportError:
                logger.warning("openai package not installed.")

        # Anthropic
        if os.environ.get("ANTHROPIC_API_KEY"):
            try:
                from anthropic import Anthropic
                self.anthropic_client = Anthropic()
            except ImportError:
                logger.warning("anthropic package not installed.")

        # Gemini
        if os.environ.get("GEMINI_API_KEY"):
            try:
                import google.generativeai as genai
                genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
                self.gemini_client = genai
            except ImportError:
                logger.warning("google-generativeai package not installed.")

        # Mistral
        self.mistral_api_key = os.environ.get("MISTRAL_API_KEY")

    def generate_chat_completion(
        self, 
        model: str, 
        messages: List[Dict[str, Any]], 
        tools: Optional[List[Dict[str, Any]]] = None,
        provider: Optional[str] = None,
        api_key: Optional[str] = None
    ) -> LLMResponse:
        logger.info(f"LLM request to model={model} (provider: {provider}) with {len(messages)} messages")
        
        # Override configuration dynamically if custom keys are passed from client
        if provider == "gemini" and api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                self.gemini_client = genai
                model = "gemini-1.5-flash"
            except Exception as e:
                logger.error(f"Failed to configure custom Gemini key: {e}")
        elif provider == "mistral" and api_key:
            self.mistral_api_key = api_key
            model = "open-mistral-7b"

        # Determine provider
        if (model.startswith("gpt") or model.startswith("o1") or model.startswith("o3")) and self.openai_client:
            return self._call_openai(model, messages, tools)
        elif model.startswith("claude") and self.anthropic_client:
            return self._call_anthropic(model, messages, tools)
        elif (model.startswith("gemini") or provider == "gemini") and self.gemini_client:
            gemini_model = model if model.startswith("gemini") else "gemini-1.5-flash"
            return self._call_gemini(gemini_model, messages, tools)
        elif (model.startswith("mistral") or provider == "mistral") and self.mistral_api_key:
            mistral_model = model if model.startswith("mistral") else "open-mistral-7b"
            return self._call_mistral(mistral_model, messages, tools)
        else:
            # Fallback to mock or first available configured client
            if self.openai_client:
                return self._call_openai(model, messages, tools)
            elif self.anthropic_client:
                return self._call_anthropic(model, messages, tools)
            elif self.gemini_client:
                return self._call_gemini(model, messages, tools)
            elif self.mistral_api_key:
                return self._call_mistral(model, messages, tools)
            else:
                return self._mock_call(model, messages, tools)

    def _call_mistral(self, model: str, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]) -> LLMResponse:
        if not self.mistral_api_key:
            raise ValueError("Mistral API key not configured.")
        import httpx
        url = "https://api.mistral.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.mistral_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]
            
        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            
            choice = data["choices"][0]
            message = choice["message"]
            content = message.get("content")
            
            tool_calls = []
            if message.get("tool_calls"):
                for tc in message["tool_calls"]:
                    import json
                    args = tc["function"]["arguments"]
                    if isinstance(args, str):
                        args = json.loads(args)
                    tool_calls.append({
                        "id": tc.get("id", ""),
                        "name": tc["function"]["name"],
                        "arguments": args
                    })
                    
            return LLMResponse(content=content, tool_calls=tool_calls)
        except Exception as e:
            logger.error(f"Mistral API call failed: {e}")
            raise ValueError(f"Mistral API call failed: {e}")

    def _call_openai(self, model: str, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]) -> LLMResponse:
        if not self.openai_client:
            raise ValueError("OpenAI API key not configured or client initialization failed.")
        
        kwargs = {}
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
            
        response = self.openai_client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs
        )
        
        message = response.choices[0].message
        content = message.content
        
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                import json
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments)
                })
                
        return LLMResponse(content=content, tool_calls=tool_calls)

    def _call_anthropic(self, model: str, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]) -> LLMResponse:
        if not self.anthropic_client:
            raise ValueError("Anthropic API key not configured or client initialization failed.")
        
        # Anthropic separate system prompt out of messages list
        system_prompt = ""
        anthropic_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                anthropic_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
                
        kwargs = {}
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            # Convert tools to Anthropic format
            anthropic_tools = []
            for t in tools:
                anthropic_tools.append({
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": {
                        "type": "object",
                        "properties": t.get("parameters", {}).get("properties", {}),
                        "required": t.get("parameters", {}).get("required", [])
                    }
                })
            kwargs["tools"] = anthropic_tools

        response = self.anthropic_client.messages.create(
            model=model,
            messages=anthropic_messages,
            max_tokens=4096,
            **kwargs
        )
        
        content = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.input
                })
                
        return LLMResponse(content=content if content else None, tool_calls=tool_calls)

    def _call_gemini(self, model: str, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]) -> LLMResponse:
        if not self.gemini_client:
            raise ValueError("Gemini API key not configured or client initialization failed.")
        
        # Setup model config
        # Simple implementation using google.generativeai chat interface
        system_instruction = None
        gemini_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_instruction = msg["content"]
            else:
                role = "user" if msg["role"] == "user" else "model"
                gemini_messages.append({
                    "role": role,
                    "parts": [msg["content"]]
                })
                
        # Note: In a fully-hardened implementation we would translate tools to Gemini Function Declarations.
        # For Milestone 1, we implement content generation with system_instruction.
        model_instance = self.gemini_client.GenerativeModel(
            model_name=model,
            system_instruction=system_instruction
        )
        
        # Convert messages to gemini structure
        response = model_instance.generate_content(gemini_messages)
        return LLMResponse(content=response.text)

    def _mock_call(self, model: str, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]) -> LLMResponse:
        logger.warning("No LLM API keys configured. Returning mock response.")
        
        # Simple mock reasoning that parses instructions
        last_user_message = ""
        for msg in reversed(messages):
            if msg["role"] == "user":
                last_user_message = msg["content"]
                break
                
        # Check if we already have tool results in the message history
        has_tool_results = any(msg["role"] == "tool" for msg in messages)
        
        # Mock tool calling logic for tests
        if tools and "calculate" in last_user_message.lower() and not has_tool_results:
            # Trigger a calculator mock call
            expr = "2 + 2"
            parts = last_user_message.lower().split("calculate")
            if len(parts) > 1:
                expr = parts[1].strip()
            return LLMResponse(
                content="Let me use the calculator to compute that value.",
                tool_calls=[{
                    "id": "call_mock_calc_123",
                    "name": "calculate",
                    "arguments": {"expression": expr}
                }]
            )
            
        if has_tool_results:
            # Find the last tool result
            tool_content = "112"
            for msg in reversed(messages):
                if msg["role"] == "tool":
                    tool_content = msg["content"]
                    break
            return LLMResponse(
                content=f"The calculation result is {tool_content}."
            )
            
        return LLMResponse(
            content=f"Mock response for task. Last query: '{last_user_message}'."
        )

    def get_embedding(self, text: str) -> List[float]:
        """Generate a 1536-dimensional vector embedding for the input text."""
        if self.openai_client:
            try:
                response = self.openai_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=[text]
                )
                return response.data[0].embedding
            except Exception as e:
                logger.error(f"OpenAI embedding error: {e}")
        
        # Pure Python deterministic bag-of-words embedding projected to 1536 dimensions
        import re
        import random
        
        words = re.findall(r'\w+', text.lower())
        vector = [0.0] * 1536
        for w in words:
            # Stable DJB2 hash to map the word to a vector index
            h = 5381
            for char in w:
                h = ((h << 5) + h) + ord(char)
            idx = abs(h) % 1536
            vector[idx] += 1.0
            
        # Add deterministic stable noise to break symmetry and ensure vector is non-zero
        h_text = 5381
        for char in text:
            h_text = ((h_text << 5) + h_text) + ord(char)
        random.seed(h_text)
        
        for i in range(1536):
            vector[i] += random.uniform(-0.01, 0.01)
            
        # Normalize the vector to unit length
        norm = sum(x*x for x in vector) ** 0.5
        if norm > 0:
            vector = [x / norm for x in vector]
            
        return vector

