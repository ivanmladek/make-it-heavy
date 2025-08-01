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
        """Make OpenRouter API call with tools and conservative generation params to reduce token/cost."""
        try:
            response = self.client.chat.completions.create(
                model=model or self.config['openrouter']['model'],
                messages=messages,
                tools=self.tools,
                temperature=0.2,
                max_tokens=self.config.get('openrouter', {}).get('max_tokens', 512),
                top_p=0.9,
                extra_body={
                    "provider": {
                        "sort": "throughput"
                    }
                }
            )
            return response
        except Exception as e:
            raise Exception(f"LLM call failed: {str(e)}")
    
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
        """Run the agent with user input and return FULL conversation content (cost-aware)."""
        # System prompt trimmed to reduce tokens
        sys_prompt = self.config.get('system_prompt', '')
        if len(sys_prompt) > 1200:
            sys_prompt = sys_prompt[:1200]

        # Initialize messages with system prompt and user input (truncate user input hard)
        trimmed_user = user_input
        if len(trimmed_user) > 2000:
            trimmed_user = trimmed_user[:2000]

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": trimmed_user}
        ]
        
        full_response_content = []
        max_iterations = min(2, self.config.get('agent', {}).get('max_iterations', 10))  # cap to 2 to limit tokens
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            if not self.silent:
                print(f"🔄 Agent iteration {iteration}/{max_iterations}")
            
            response = self.call_llm(messages, model)
            assistant_message = response.choices[0].message

            # Ensure content is not None
            content_text = assistant_message.content or ""
            # Trim assistant content to avoid blow-up next round
            if len(content_text) > 1500:
                content_text = content_text[:1500]

            messages.append({
                "role": "assistant",
                "content": content_text,
                "tool_calls": assistant_message.tool_calls
            })
            
            if content_text:
                full_response_content.append(content_text)
            
            if assistant_message.tool_calls:
                if not self.silent:
                    print(f"🔧 Agent making {len(assistant_message.tool_calls)} tool call(s)")
                task_completed = False
                for tool_call in assistant_message.tool_calls:
                    if not self.silent:
                        print(f"   📞 Calling tool: {tool_call.function.name}")
                    tool_result = self.handle_tool_call(tool_call)
                    messages.append(tool_result)
                    if tool_call.function.name == "mark_task_complete":
                        task_completed = True
                        if not self.silent:
                            print("✅ Task completion tool called - exiting loop")
                        return "\n\n".join(full_response_content)
                if task_completed:
                    return "\n\n".join(full_response_content)
            else:
                if not self.silent:
                    print("💭 Agent responded without tool calls - continuing loop")
        
        return "\n\n".join(full_response_content) if full_response_content else "No content generated."