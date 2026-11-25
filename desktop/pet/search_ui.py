"""Exact, scoped search input and readback; no message submission or replay."""
import json
import logging
import re
import unicodedata
from .agent_bridge import AgentDesktopBridge, AgentBridgeError, unique_ref_for_point, _LINE
from .desktop_guard import current_window
from .screen_context import _binary, _private_directory
from .task_tools import GoalUIReferences, required_search_query


def _normal(text):
    return ' '.join(unicodedata.normalize('NFC',text).casefold().split())


def search_input_query(goal, args, line):
    query=required_search_query(goal)
    match=_LINE.search(line)
    if not query or not match or not isinstance(args.get('text'),str): return None
    role=re.sub(r'[^a-z0-9]','',match[3].casefold())
    label=match[4]
    if role not in ('edit','textfield','textarea','searchfield','searchbox','combobox','textbox'): return None
    if not re.search(r'tìm|tim|search',label,re.I): return None
    if re.search(r'address|địa chỉ|nhập url|type a url|omnibox|gần đây|recent',label,re.I): return None
    if args.get('clear') or args.get('press_enter') or _normal(args['text'])!=_normal(query): return None
    return query


def _read(bridge,point,line):
    snapshot=bridge.snapshot(max_depth=30)
    ref=unique_ref_for_point(snapshot,point,line,'type')
    reply=bridge.get_value(ref)
    value=(reply.get('data') or {}).get('value')
    if not reply.get('ok') or not isinstance(value,str):
        raise AgentBridgeError('Search field readback unavailable')
    return snapshot,ref,value


def run_search_input(guard,window,args,query,*,bridge_type=AgentDesktopBridge):
    guard._agent_phase='preflight'
    line=guard._target_line(args.get('loc'))
    if current_window()!=window or search_input_query(getattr(guard,'_agent_goal',''),args,line)!=query:
        raise AgentBridgeError('Search input no longer matches current request')
    binary=_binary()
    if not binary: raise AgentBridgeError('Agent desktop unavailable')
    guard._agent_phase='session'
    authorize=lambda op,ref,value: op in ('search','type') and value==args['text']
    with bridge_type(binary,f'w-{window.hwnd}',lambda:current_window()==window,authorize,_private_directory) as bridge:
        guard._agent_phase='snapshot'
        snap,ref,_=_read(bridge,args['loc'],line)
        pending=[snap.get('tree')]; node=None
        while pending:
            item=pending.pop()
            if not isinstance(item,dict): continue
            if item.get('ref_id')==ref: node=item; break
            pending.extend(item.get('children') or [])
        guard._agent_phase='input'
        # Choose the delivery method BEFORE input. Never switch methods after
        # a rejected/uncertain action, and never press Enter in a search step.
        if node and 'SetValue' in (node.get('available_actions') or []):
            reply=bridge.set_value_for_search(ref,args['text'])
        else:
            if not bridge.is_focused(ref):
                bridge.focus_for_type(ref,args['text'])
                _,ref,_=_read(bridge,args['loc'],line)
                if not bridge.is_focused(ref): raise AgentBridgeError('Search field focus not verified')
            reply=bridge.act('type',ref,text=args['text'])
        if not reply.get('ok'): raise AgentBridgeError('Search input delivery uncertain; no retry')
        _,_,value=_read(bridge,args['loc'],line)
        if current_window()!=window or _normal(value)!=_normal(query):
            raise AgentBridgeError('Search input value differs; no retry')
        return {'delivery':'delivered_verified','element_value_verified':True,
                'instruction':'Search field read back correctly. InspectUI again before Finish. No message sent.'}


def augment_search_observation(guard,window,text,*,bridge_type=AgentDesktopBridge):
    """Add evidence only from a NEW exact-field value read, not a prior receipt."""
    query=required_search_query(getattr(guard,'_agent_goal',''))
    if not query or not getattr(guard,'grant',''): return text
    refs=GoalUIReferences(); refs.project(text)
    candidates=refs.search_input_refs()
    if len(candidates)!=1: return text
    point=refs.targets[candidates[0]]
    line=guard._target_line(point,text)
    if not line:
        logging.info('SEARCH_READBACK code=target_unresolved')
        return text
    if not guard._window_allowed(window) or current_window()!=window:
        logging.info('SEARCH_READBACK code=scope_changed')
        return text
    binary=_binary()
    if not binary: return text
    try:
        guard._check()
        with bridge_type(binary,f'w-{window.hwnd}',lambda:current_window()==window,
                         lambda *args:False,_private_directory) as bridge:
            _,_,value=_read(bridge,point,line)
        matched=current_window()==window and _normal(value)==_normal(query)
        logging.info('SEARCH_READBACK matched=%s',matched)
        if matched:
            # Prefix so the verified value survives a later text-size cap.
            return 'Verified search field value: '+value+'\n'+text
    except AgentBridgeError:
        logging.info('SEARCH_READBACK code=unavailable')
    return text
