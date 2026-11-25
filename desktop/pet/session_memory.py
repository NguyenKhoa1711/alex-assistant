"""Ephemeral local session context; nothing is written to disk."""
from __future__ import annotations
import re
import unicodedata

_STOP = frozenset('anh chi ban minh toi chung ta cua cac mot nhung nhu the nao gi la cho duoc voi trong nay do no day roi vay cua ve co khong hay cho biet len xuong them luc truoc sau cung hay vi sao tai sao la va mot nhieu nguoi nao la dieu gi'.split())

def _fold(text):
    return ''.join(c for c in unicodedata.normalize('NFD',text.casefold().replace('đ','d'))
                   if unicodedata.category(c)!='Mn')

def _words(text):
    return {w for w in re.findall(r'[a-z0-9]+',_fold(text)) if len(w)>=3 and w not in _STOP}

def contextual_followup(question):
    """Pronouns need local session context; don't send an unresolved question to web search."""
    text=_fold(question).strip()
    if re.search(r'\b(?:cai do|dieu do|nguoi do|nguoi ay|vi do|o do|'
                 r'dieu nay|van de nay|chuyen nay|cau do|cau nay|cai nay|'
                 r'truong hop do|truong hop nay|ong ay|ba ay|the con|con no)\b',text):
        return True
    if re.search(r'\b(?:nó|họ|đó|ấy)\b',question, re.IGNORECASE):
        return True
    return bool(re.match(r'^(?:vay|the)\b',text) and len(text.split())<=9
                and not re.search(r'\b(?:thoi tiet|gia vang|ty gia|tin tuc)\b',text))

def _clip(value, limit):
    if len(value)<=limit:return value
    if limit <= 3:return value[:limit]
    keep=limit-3
    head=keep*3//4
    return value[:head].rstrip()+' … '+value[-(keep-head):].lstrip()

def context_history(history, question, max_turns=5, char_budget=3200):
    """Recall recent turns plus one relevant older turn, bounded for the local model."""
    if not history or max_turns<1:return []
    n=len(history);recent_count=min(4,max_turns,n)
    selected=list(range(n-recent_count,n))
    if n>recent_count and max_turns>recent_count:
        text=_fold(question)
        if re.search(r'\b(?:luc dau|ban dau|dau tien|cau dau|dau cuoc tro chuyen)\b',text):
            selected.insert(0,0)
        else:
            wanted=_words(question)
            best_idx=None;best_score=0
            if wanted:
                for i,(user,assistant) in enumerate(history[:n-recent_count]):
                    score=len(wanted & _words(user)) * 2 + len(wanted & _words(assistant))
                    if score>=best_score and score>0:
                        best_idx,best_score=i,score
            if best_idx is not None:selected.insert(0,best_idx)
    out=[]
    # Bound each pair before the aggregate budget so one long answer can't erase context.
    for i in reversed(selected):
        user,answer=history[i]
        if not isinstance(user,str) or not isinstance(answer,str):continue
        user=_clip(user,340);answer=_clip(answer,300)
        cost=len(user)+len(answer)
        if cost>char_budget:
            if char_budget<160:break
            user=_clip(user,char_budget//2-4);answer=_clip(answer,char_budget//2-4)
            cost=len(user)+len(answer)
        out.insert(0,(user,answer));char_budget-=cost
    return out
