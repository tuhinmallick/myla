import os
import datetime
from ._tools import get_tool
from .tools import Tool, Context
from . import runs, assistants
from .messages import create as create_message
from .messages import list as list_messages, create as create_message, MessageCreate
from ._logging import logger as log
from . import llms

async def chat_complete(run: runs.RunRead, iter):
    try:
        thread_id = run.thread_id

        messages = []

        model = run.model
        instructions = run.instructions
        tools = run.tools
        run_metadata = run.metadata if run.metadata else {}

        # Get Assistant
        assistant = assistants.get(id=run.assistant_id)
        assistant_id = None
        if assistant is not None:
            assistant_id = assistant.id

            if not instructions:
                instructions = assistant.instructions
            if not model:
                model = assistant.model
            if not tools or len(tools) == 0:
                tools = assistant.tools

            a_metadata = assistant.metadata if assistant.metadata else {}
            a_metadata.update(run_metadata)
            run_metadata = a_metadata

        # set instructions
        if instructions is not None:
            messages.append({
                "role": "system",
                "content": instructions
            })

        # llm_args
        llm_args = run_metadata['llm_args'] if 'llm_args' in run_metadata else {"temperature": 0.0}

        # Laod history
        history = list_messages(thread_id=thread_id, order="desc", limit=4).data
        history = history[::-1]

        # append history to messages
        for h in history:
            role = h.role
            content = h.content[0]
            if content.type == "text":
                content = content.text[0].value
            messages.append({
                "role": role,
                "content": content
            })

        runs.update(
            id=run.id,
            status="in_progress",
            started_at=int(round(datetime.datetime.now().timestamp()))
        )

        # Run tools
        context: Context = await run_tools(tools=tools, messages=messages, run_metadata=run_metadata)
        llm_args.update(context.llm_args)

        log.debug(f"Context after tools: {context}")

        genereated = []

        if context.is_completed:
            completed_msg = context.messages[-1]["content"]
            genereated.append(completed_msg)
            iter.put(completed_msg)
        else:
            combined_messages = combine_system_messages(messages=context.messages)
            llm = llms.get(model_name=model)
            resp = await llm.chat(messages=combined_messages, stream=True, **llm_args)

            async for c in resp:
                if c is not None:
                    genereated.append(c)
                    await iter.put(c)

        msg_create = MessageCreate(
            role="assistant",
            content=''.join(genereated),
            metadata=context.message_metadata
        )
        create_message(thread_id=thread_id, message=msg_create, assistant_id=assistant_id, run_id=run.id)

        runs.update(
            id=run.id,
            status="completed",
            completed_at=int(round(datetime.datetime.now().timestamp()))
        )
        await iter.put(None) # Completed
    except Exception as e:
        log.warn(f"LLM Failed: {e}")
        log.debug("LLM exc: ", exc_info=e)
        
        runs.update(id=run.id,
            status="failed",
            last_error={
                "code": "server_error",
                "message": str(e)
            },
            failed_at=int(round(datetime.datetime.now().timestamp()))
        )
        await iter.put(e)
        await iter.put(None) #DONE

async def run_tools(tools, messages, run_metadata):
    run_metadata = run_metadata if run_metadata else {}

    context = Context(messages=messages, run_metadata=run_metadata)

    if not tools:
        tools = []

    for tool in tools:
        tool_name = tool["type"]

        #if tool_name.startswith("$"):
        #    # 由 LLM 决定是否执行, 并确定执行参数

        tool_instance: Tool = get_tool(tool_name)

        if not isinstance(tool_instance, Tool):
            log.warn(f"tool instance is not a Tool: {tool_name}")
            continue

        await tool_instance.execute(context=context)
        if context.is_completed:
            return context

    return context

def combine_system_messages(messages):
    """Combine multiple system messages into one"""
    normal_messages = []
    system_message = []
    for msg in messages:
        if msg["role"] == "system":
            system_message.append(msg["content"])
        else:
            normal_messages.append(msg)
    r_messages = [
        {
            "role": "system",
            "content": '\n'.join(system_message)
        }
    ]
    r_messages.extend(normal_messages)
    return r_messages
