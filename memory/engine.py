import json
import logging
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from storage.database import SemanticMemoryTable

logger = logging.getLogger("agentos.memory.engine")

class MemoryEngine:
    def __init__(self, llm_gateway=None):
        self.llm_gateway = llm_gateway

    # --- Working Memory Operations ---
    def get_working_memory(self, messages: List[Dict[str, Any]], limit: int = 16384) -> List[Dict[str, Any]]:
        """Returns working memory, compressing it if context exceeds limit."""
        # Simple compression logic: if there are more than 15 messages, we summarize the older ones.
        if len(messages) > 15:
            logger.info("Working memory limit exceeded. Compressing older history...")
            return self._compress_working_memory(messages)
        return messages

    def _compress_working_memory(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self.llm_gateway:
            # Fallback if no LLM gateway configured
            return messages[-10:]
            
        system_msg = None
        to_summarize = []
        to_keep = messages[-6:]  # Keep last 6 messages intact
        
        for msg in messages[:-6]:
            if msg["role"] == "system":
                system_msg = msg
            else:
                to_summarize.append(f"{msg['role']}: {msg['content']}")
                
        if not to_summarize:
            return messages
            
        summary_prompt = (
            "Summarize the following conversation history between the AI agent and the user. "
            "Retain all key decisions, state changes, variables, and completed goals:\n\n"
            + "\n".join(to_summarize)
        )
        
        # Run a fast summary query
        response = self.llm_gateway.generate_chat_completion(
            model="gpt-4o",  # Default or small model
            messages=[{"role": "user", "content": summary_prompt}]
        )
        
        summary_content = response.content or "Conversation summary not available."
        
        new_messages = []
        if system_msg:
            new_messages.append(system_msg)
            
        new_messages.append({
            "role": "system",
            "content": f"Summary of previous interactions: {summary_content}"
        })
        new_messages.extend(to_keep)
        
        return new_messages

    # --- Semantic Memory Operations ---
    def save_semantic_memory(self, db: Session, agent_id: str, text: str):
        """Generates embedding for the text and saves it to the database."""
        if not self.llm_gateway:
            logger.warning("No LLM gateway configured. Saving semantic memory with mock embedding.")
            embedding = [0.0] * 1536
        else:
            embedding = self.llm_gateway.get_embedding(text)
            
        embedding_json = json.dumps(embedding)
        memory_entry = SemanticMemoryTable(
            agent_id=agent_id,
            text=text,
            embedding=embedding_json
        )
        db.add(memory_entry)
        db.commit()
        logger.info(f"Saved semantic memory for agent {agent_id}")

    def search_semantic_memory(self, db: Session, agent_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Searches semantic memories using cosine similarity in pure Python."""
        if not self.llm_gateway:
            logger.warning("No LLM gateway configured. Returning empty semantic memory search.")
            return []
            
        query_embedding = self.llm_gateway.get_embedding(query)
        
        # Retrieve all memories for the agent
        memories = db.query(SemanticMemoryTable).filter(SemanticMemoryTable.agent_id == agent_id).all()
        if not memories:
            return []
            
        results = []
        for mem in memories:
            mem_embedding = json.loads(mem.embedding)
            similarity = self._cosine_similarity(query_embedding, mem_embedding)
            results.append({
                "text": mem.text,
                "similarity": similarity,
                "created_at": mem.created_at
            })
            
        # Sort by similarity descending
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm_a = sum(a * a for a in vec1) ** 0.5
        norm_b = sum(b * b for b in vec2) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot_product / (norm_a * norm_b)
