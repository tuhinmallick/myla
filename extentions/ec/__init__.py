import json
from myla import tools
from myla.tools import Context

class ECTool(tools.Tool):
    def __init__(self, device='cpu') -> None:
        super().__init__()

        self.device = device

    async def execute(self, context: Context) -> None:
        if docs := next(
            (
                msg['content']
                for msg in context.messages
                if msg.get('type') == 'docs'
            ),
            None,
        ):
            docs = json.loads(docs)
        else:
            return
        #print(docs)
        #

    