import json
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch
from pet.gemma import GemmaChat
from pet.gemini import GeminiChat


class SearchCompletionTests(unittest.TestCase):
    def test_verified_launch_search_offers_finish_and_no_further_click_or_type(self):
        schemas=json.loads((Path(__file__).parent/'fixtures/desktop_tool_schemas.json').read_text(encoding='utf-8'))
        sent=[]; typed=False
        def backend(name,args,event):
            nonlocal typed
            sent.append(name)
            if name=='Type': typed=True
            value=('Verified search field value: alex-kiem-tra\n' if typed else '')
            value+='UI Tree:\nwindow "Messenger"\n└── (215,142) combo box "Tìm kiếm trên Messenger" [focused] [action: click]'
            if name=='Finish': value={'finished':True}
            return json.dumps({'is_error':False,'result':value})
        q='Mày hãy mở Messenger cho tao và tìm kiếm alex-kiem-tra.'
        chat=object.__new__(GemmaChat)
        chat.__dict__.update(computer=SimpleNamespace(cfg={},tools=lambda _:schemas,call=backend),
            computer_for_turn=True,computer_enabled=True,goal_task_for_turn=True,history=[],computer_original_request=q)
        offered=[]
        def stream(self,q,event):
            self.computer.call('InspectUI',{},event)
            self.computer.call('TypeUI',{'target':'ui1_0','text':'alex-kiem-tra','clear':True,'press_enter':True},event)
            self.computer.call('InspectUI',{},event)
            offered.extend(s['function']['name'] for s in self.computer.tools(event))
            self.computer.call('Finish',{'evidence':'alex-kiem-tra'},event)
            yield 'Đã tìm kiếm.'
        with patch.object(GeminiChat,'stream',stream):
            self.assertEqual(''.join(chat.stream(q,threading.Event())),'Đã tìm kiếm.')
        self.assertEqual(set(offered),{'Finish','Cancel'})
        self.assertEqual(sent,['Snapshot','Type','Snapshot','Finish'])

if __name__=='__main__': unittest.main()
