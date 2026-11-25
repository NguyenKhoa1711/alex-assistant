import unittest
from unittest.mock import patch
from pet.desktop_guard import DesktopGuard, Window
from pet.agent_bridge import AgentBridgeError
from pet.search_ui import run_search_input, augment_search_observation, search_input_query

LINE='└── (215,142) combo box "Tìm kiếm trên Messenger" [focused] [action: click]'
TREE='Focused Window:\nMessenger - Chrome\nOpened Windows:\nUI Tree:\nwindow "Messenger - Chrome"\n'+LINE
QUERY='An Mẫu'
GOAL='Mở Messenger và tìm kiếm '+QUERY


class Bridge:
    value=''; mutations=[]; corrupt=False
    def __init__(self,binary,wid,identity,authorize,private): self.identity=identity; self.authorize=authorize
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def snapshot(self,**kwargs):
        return {'tree':{'ref_id':'@s1:e1','name':'Tìm kiếm trên Messenger','role':'combobox',
                        'bounds':{'x':200,'y':130,'width':100,'height':30},'available_actions':['SetFocus','SetValue']}}
    def get_value(self,ref): return {'ok':True,'data':{'value':self.value}}
    def set_value_for_search(self,ref,text):
        assert self.identity() and self.authorize('search',ref,text)
        self.mutations.append(('set-value',ref,text))
        type(self).value='corrupted' if self.corrupt else text
        return {'ok':True,'data':{}}
    def act(self,*args,**kwargs): raise AssertionError('No input fallback allowed')


class VerifiedSearchTests(unittest.TestCase):
    def setUp(self):
        Bridge.value=''; Bridge.mutations=[]; Bridge.corrupt=False
        self.win=Window(1,123,'chrome.exe','Messenger - Chrome')
        self.guard=DesktopGuard(lambda *args:{'allowed':True,'grant':'fixture'},lambda:self.win)
        self.guard.apps=['Chrome']; self.guard.grant='fixture'; self.guard._agent_goal=GOAL; self.guard.snapshot=TREE
        self.args={'loc':[215,142],'text':QUERY,'clear':False,'press_enter':False}
        self.context=patch.multiple('pet.search_ui',current_window=lambda:self.win,_binary=lambda:'fixture-agent.exe')
        self.context.start(); self.addCleanup(self.context.stop)

    def test_search_set_value_and_fresh_readback_prove_actual_value(self):
        Bridge.value='old search'
        result=run_search_input(self.guard,self.win,self.args,QUERY,bridge_type=Bridge)
        self.assertTrue(result['element_value_verified'])
        self.assertEqual(Bridge.mutations,[('set-value','@s1:e1',QUERY)])
        observed=augment_search_observation(self.guard,self.win,TREE,bridge_type=Bridge)
        self.assertTrue(observed.startswith('Verified search field value: '+QUERY))
        Bridge.value='changed after typing'
        self.assertEqual(augment_search_observation(self.guard,self.win,TREE,bridge_type=Bridge),TREE)

    def test_corrupted_delivery_is_not_replayed(self):
        Bridge.corrupt=True
        with self.assertRaises(AgentBridgeError): run_search_input(self.guard,self.win,self.args,QUERY,bridge_type=Bridge)
        self.assertEqual(len(Bridge.mutations),1)
        self.assertEqual(augment_search_observation(self.guard,self.win,TREE,bridge_type=Bridge),TREE)

    def test_no_claim_when_value_or_window_does_not_match(self):
        Bridge.value='different'
        self.assertEqual(augment_search_observation(self.guard,self.win,TREE,bridge_type=Bridge),TREE)
        Bridge.value=QUERY
        other=Window(2,321,'chrome.exe','Other')
        self.assertEqual(augment_search_observation(self.guard,other,TREE,bridge_type=Bridge),TREE)
        self.assertFalse(Bridge.mutations)

    def test_search_spec_never_matches_composer_address_or_unrequested_text(self):
        self.assertEqual(search_input_query(GOAL,self.args,LINE),QUERY)
        for role,label in (('edit','Aa'),('edit','Address and search bar'),('button','Tìm kiếm')):
            self.assertIsNone(search_input_query(GOAL,self.args,f'└── (215,142) {role} "{label}" [action: fill]'))
        self.assertIsNone(search_input_query(GOAL,{**self.args,'text':'wrong'},LINE))
        self.assertIsNone(search_input_query(GOAL,{**self.args,'press_enter':True},LINE))

if __name__=='__main__': unittest.main()
