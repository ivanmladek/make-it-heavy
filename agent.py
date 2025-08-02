import json
import yaml
from openai import OpenAI
from tools import discover_tools

class OpenRouterAgent:
    def __init__(self, config_path="config.yaml", silent=False):
        # Load configuration
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Silent mode for orchestrator (suppresses debug output)
        self.silent = silent
        
        # Initialize OpenAI client with OpenRouter
        self.client = OpenAI(
            base_url=self.config['openrouter']['base_url'],
            api_key=self.config['openrouter']['api_key']
        )
        
        # Discover tools dynamically
        self.discovered_tools = discover_tools(self.config, silent=self.silent)
        
        # Build OpenRouter tools array
        self.tools = [tool.to_openrouter_schema() for tool in self.discovered_tools.values()]
        
        # Build tool mapping
        self.tool_mapping = {name: tool.execute for name, tool in self.discovered_tools.items()}
    
    
    def call_llm(self, messages, model=None):
        """Make OpenRouter API call with tools (no cost guardrails). Return None on failure or slow responses."""
        import time as _time
        target_model = model or self.config['openrouter']['model']
        max_retries = 2
        backoffs = [0.5, 1.0]
        start = _time.monotonic()
        max_wait_seconds = 12.0

        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=target_model,
                    messages=messages,
                    tools=self.tools,
                    extra_body={"provider": {"sort": "throughput"}},
                )
                # Validate response structure
                choices = getattr(response, "choices", None)
                if not choices:
                    return None
                first = choices[0]
                msg = getattr(first, "message", None)
                if msg is None and isinstance(first, dict):
                    msg = first.get("message")
                if msg is None:
                    return None
                content = getattr(msg, "content", None)
                if content is None and isinstance(msg, dict):
                    content = msg.get("content")
                if content is None:
                    return None
                return response
            except Exception as e:
                if not self.silent:
                    print(f"[LLM ERROR] attempt {attempt+1} failed for model {target_model}: {e}")
                if attempt < max_retries:
                    # Check time budget
                    elapsed = _time.monotonic() - start
                    if elapsed > max_wait_seconds:
                        return None
                    _time.sleep(backoffs[attempt])
                    continue
                return None
    
    def handle_tool_call(self, tool_call):
        """Handle a tool call and return the result message"""
        try:
            # Extract tool name and arguments
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            
            # Call appropriate tool from tool_mapping
            if tool_name in self.tool_mapping:
                tool_result = self.tool_mapping[tool_name](**tool_args)
            else:
                tool_result = {"error": f"Unknown tool: {tool_name}"}
            
            # Return tool result message
            return {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": json.dumps(tool_result)
            }
        
        except Exception as e:
            return {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": json.dumps({"error": f"Tool execution failed: {str(e)}"})
            }
    
    def run(self, user_input: str, model: str = None):
        """Run the agent with user input and return FULL conversation content (no guardrails, resilient to provider errors)."""
        messages = [
            {"role": "system", "content": self.config.get('system_prompt', '')},
            {"role": "user", "content": user_input}
        ]
        full_response_content = []
        max_iterations = self.config.get('agent', {}).get('max_iterations', 10)
        iteration = 0
        fallback = "ACK"

        while iteration < max_iterations:
            iteration += 1
            if not self.silent:
                print(f"🔄 Agent iteration {iteration}/{max_iterations}")

            response = self.call_llm(messages, model)
            if response is None:
                # Provider error or malformed; append minimal fallback to keep the game flowing
                messages.append({"role": "assistant", "content": fallback})
                full_response_content.append(fallback)
                break

            # Extract assistant message robustly
            first = response.choices[0]
            assistant_message = getattr(first, "message", None)
            if assistant_message is None and isinstance(first, dict):
                assistant_message = first.get("message", {})

            # Content and tool calls with defensive access
            if isinstance(assistant_message, dict):
                content_text = assistant_message.get("content", "") or ""
                tool_calls = assistant_message.get("tool_calls", []) or []
            else:
                content_text = getattr(assistant_message, "content", "") or ""
                tool_calls = getattr(assistant_message, "tool_calls", []) or []

            messages.append({
                "role": "assistant",
                "content": content_text,
                "tool_calls": tool_calls
            })
            if content_text:
                full_response_content.append(content_text)

            if tool_calls:
                if not self.silent:
                    try:
                        print(f"🔧 Agent making {len(tool_calls)} tool call(s)")
                    except Exception:
                        print("🔧 Agent making tool call(s)")
                task_completed = False
                for tool_call in tool_calls:
                    try:
                        tool_name = getattr(tool_call.function, "name", None)
                    except Exception:
                        tool_name = None
                    if not self.silent and tool_name:
                        print(f"   📞 Calling tool: {tool_name}")
                    tool_result = self.handle_tool_call(tool_call)
                    messages.append(tool_result)
                    if tool_name == "mark_task_complete":
                        task_completed = True
                        if not self.silent:
                            print("✅ Task completion tool called - exiting loop")
                        return "\n\n".join(full_response_content) if full_response_content else ""
                if task_completed:
                    return "\n\n".join(full_response_content) if full_response_content else ""
            else:
                if not self.silent:
                    print("💭 Agent responded without tool calls - continuing loop")

            # For this orchestrated usage, we only need the first assistant turn
            break

        return "\n\n".join(full_response_content) if full_response_content else fallback