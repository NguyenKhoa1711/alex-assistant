import unittest
from pet.task_tools import GoalUIReferences
from pet.desktop_guard import DesktopGuard
from pet.agent_bridge import unique_ref_for_point


class NativeSearchRoleTests(unittest.TestCase):
    def test_native_spaced_input_roles_flow_through_projection_guard_and_agent_match(self):
        for native,agent in (('combo box','combobox'),('search field','searchfield'),('edit','edit')):
            with self.subTest(role=native):
                line=f'└── (215,142) {native} "Tìm kiếm trên Messenger" [focused] [action: click]'
                refs=GoalUIReferences()
                refs.project('UI Tree:\nwindow "Messenger"\n'+line)
                selected=refs.search_input_refs()
                self.assertEqual(len(selected),1)
                self.assertEqual(refs.resolve('TypeUI',{'target':selected[0],'text':'alex-kiem-tra'}),
                                 ('Type',{'text':'alex-kiem-tra','loc':[215,142]}))
                guard=DesktopGuard(); guard.snapshot=line
                actual=guard._target_line([215,142])
                self.assertEqual(actual,line)
                snap={'tree':{'ref_id':'@s1:e1','name':'Tìm kiếm trên Messenger','role':agent,
                              'bounds':{'x':200,'y':130,'width':100,'height':30},'available_actions':['SetFocus','SetValue']}}
                self.assertEqual(unique_ref_for_point(snap,[215,142],actual,'type'),'@s1:e1')

    def test_spaced_noneditable_roles_stay_blocked(self):
        refs=GoalUIReferences()
        refs.project('UI Tree:\nwindow "Messenger"\n'
                     '├── (1,2) list item "Tìm kiếm gần đây" [action: click]\n'
                     '└── (3,4) menu item "Search" [action: click]')
        self.assertEqual(refs.search_input_refs(),[])

if __name__=='__main__': unittest.main()
