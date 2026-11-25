"""Multilingual TTS preprocessing for Vietnamese, English, and Mandarin Chinese (Hanzi & Pinyin)."""
from __future__ import annotations

import ctypes
import functools
import os
from pathlib import Path
import re
import sys
import threading
import unicodedata

# ── 1. Mandarin Pinyin Tables & Syllable Converter ──────────────────────────

_PINYIN_TONE_CHAR_MAP: dict[str, tuple[str, int]] = {
    'ā': ('a', 1), 'á': ('a', 2), 'ǎ': ('a', 3), 'à': ('a', 4),
    'ē': ('e', 1), 'é': ('e', 2), 'ě': ('e', 3), 'è': ('e', 4),
    'ī': ('i', 1), 'í': ('i', 2), 'ǐ': ('i', 3), 'ì': ('i', 4),
    'ō': ('o', 1), 'ó': ('o', 2), 'ǒ': ('o', 3), 'ò': ('o', 4),
    'ū': ('u', 1), 'ú': ('u', 2), 'ǔ': ('u', 3), 'ù': ('u', 4),
    'ǖ': ('v', 1), 'ǘ': ('v', 2), 'ǚ': ('v', 3), 'ǜ': ('v', 4), 'ü': ('v', 5),
}

# Characters that ONLY appear in Pinyin (macrons, carons, u-diaeresis) and NEVER in Vietnamese
_STRICT_PINYIN_CHARS = set('āēīōūǎěǐǒǔǖǘǚǜüĀĒĪŌŪǍĚǏǑǓǕǗǙǛÜ')

_PINYIN_INITIALS = (
    'zh', 'ch', 'sh',
    'b', 'p', 'm', 'f',
    'd', 't', 'n', 'l',
    'g', 'k', 'h',
    'j', 'q', 'x',
    'r', 'z', 'c', 's',
    'y', 'w', '',
)

_PINYIN_FINALS = {
    'a', 'o', 'e', 'ai', 'ei', 'ao', 'ou', 'an', 'en', 'ang', 'eng', 'er', 'ong',
    'i', 'ia', 'io', 'ie', 'iai', 'iao', 'iu', 'iou', 'ian', 'in', 'iang', 'ing', 'iong',
    'u', 'ua', 'uo', 'uai', 'ui', 'uei', 'uan', 'un', 'uen', 'uang', 'ueng',
    'v', 've', 'ue', 'van', 'vn',
}

# Valid base Pinyin syllables
_VALID_PINYIN_SYLLABLES: set[str] = {
    'a', 'ai', 'an', 'ang', 'ao',
    'ba', 'bai', 'ban', 'bang', 'bao', 'bei', 'ben', 'beng', 'bi', 'bian', 'biao', 'bie', 'bin', 'bing', 'bo', 'bu',
    'ca', 'cai', 'can', 'cang', 'cao', 'ce', 'cen', 'ceng', 'ci', 'cong', 'cou', 'cu', 'cuan', 'cui', 'cun', 'cuo',
    'cha', 'chai', 'chan', 'chang', 'chao', 'che', 'chen', 'cheng', 'chi', 'chong', 'chou', 'chu', 'chua', 'chuai', 'chuan', 'chuang', 'chui', 'chun', 'chuo',
    'da', 'dai', 'dan', 'dang', 'dao', 'de', 'dei', 'den', 'deng', 'di', 'dia', 'dian', 'diao', 'die', 'ding', 'diu', 'dong', 'dou', 'du', 'duan', 'dui', 'dun', 'duo',
    'e', 'ei', 'en', 'eng', 'er',
    'fa', 'fan', 'fang', 'fei', 'fen', 'feng', 'fo', 'fou', 'fu',
    'ga', 'gai', 'gan', 'gang', 'gao', 'ge', 'gei', 'gen', 'geng', 'gong', 'gou', 'gu', 'gua', 'guai', 'guan', 'guang', 'gui', 'gun', 'guo',
    'ha', 'hai', 'han', 'hang', 'hao', 'he', 'hei', 'hen', 'heng', 'hong', 'hou', 'hu', 'hua', 'huai', 'huan', 'huang', 'hui', 'hun', 'huo',
    'ji', 'jia', 'jian', 'jiang', 'jiao', 'jie', 'jin', 'jing', 'jiong', 'jiu', 'ju', 'juan', 'jue', 'jun',
    'ka', 'kai', 'kan', 'kang', 'kao', 'ke', 'kei', 'ken', 'keng', 'kong', 'kou', 'ku', 'kua', 'kuai', 'kuan', 'kuang', 'kui', 'kun', 'kuo',
    'la', 'lai', 'lan', 'lang', 'lao', 'le', 'lei', 'leng', 'li', 'lia', 'lian', 'liang', 'liao', 'lie', 'lin', 'ling', 'liu', 'lo', 'long', 'lou', 'lu', 'luan', 'lun', 'luo', 'lv', 'lve', 'lue',
    'ma', 'mai', 'man', 'mang', 'mao', 'me', 'mei', 'men', 'meng', 'mi', 'mian', 'miao', 'mie', 'min', 'ming', 'miu', 'mo', 'mou', 'mu',
    'na', 'nai', 'nan', 'nang', 'nao', 'ne', 'nei', 'nen', 'neng', 'ni', 'nian', 'niang', 'niao', 'nie', 'nin', 'ning', 'niu', 'nong', 'nou', 'nu', 'nuan', 'nun', 'nuo', 'nv', 'nve', 'nue',
    'o', 'ou',
    'pa', 'pai', 'pan', 'pang', 'pao', 'pei', 'pen', 'peng', 'pi', 'pian', 'piao', 'pie', 'pin', 'ping', 'po', 'pou', 'pu',
    'qi', 'qia', 'qian', 'qiang', 'qiao', 'qie', 'qin', 'qing', 'qiong', 'qiu', 'qu', 'quan', 'que', 'qun',
    'ran', 'rang', 'rao', 're', 'ren', 'reng', 'ri', 'rong', 'rou', 'ru', 'rua', 'ruan', 'rui', 'run', 'ruo',
    'sa', 'sai', 'san', 'sang', 'sao', 'se', 'sen', 'seng', 'si', 'song', 'sou', 'su', 'suan', 'sui', 'sun', 'suo',
    'sha', 'shai', 'shan', 'shang', 'shao', 'she', 'shei', 'shen', 'sheng', 'shi', 'shou', 'shu', 'shua', 'shuai', 'shuan', 'shuang', 'shui', 'shun', 'shuo',
    'ta', 'tai', 'tan', 'tang', 'tao', 'te', 'tei', 'teng', 'ti', 'tian', 'tiao', 'tie', 'ting', 'tong', 'tou', 'tu', 'tuan', 'tui', 'tun', 'tuo',
    'wa', 'wai', 'wan', 'wang', 'wei', 'wen', 'weng', 'wo', 'wu',
    'xi', 'xia', 'xian', 'xiang', 'xiao', 'xie', 'xin', 'xing', 'xiong', 'xiu', 'xu', 'xuan', 'xue', 'xun',
    'ya', 'yan', 'yang', 'yao', 'ye', 'yi', 'yin', 'ying', 'yo', 'yong', 'you', 'yu', 'yuan', 'yue', 'yun',
    'za', 'zai', 'zan', 'zang', 'zao', 'ze', 'zei', 'zen', 'zeng', 'zi', 'zong', 'zou', 'zu', 'zuan', 'zui', 'zun', 'zuo',
    'zha', 'zhai', 'zhan', 'zhang', 'zhao', 'zhe', 'zhei', 'zhen', 'zheng', 'zhi', 'zhong', 'zhou', 'zhu', 'zhua', 'zhuai', 'zhuan', 'zhuang', 'zhui', 'zhun', 'zhuo',
}

# Syllables with acute/grave accents that could only be Pinyin (never valid Vietnamese words)
_NON_VI_PINYIN_BASES: set[str] = {
    s for s in _VALID_PINYIN_SYLLABLES
    if s.startswith(('zh', 'sh', 'j', 'z', 'w', 'q'))
    or (s.startswith('y') and s not in ('y', 'ye', 'yen'))
    or s.endswith(('ian', 'iao', 'uan', 'uang', 'iong', 'uo', 'ei', 'ou', 'er', 'ue', 've', 'ing'))
    or s in ('xie', 'xia', 'xin', 'ren', 'ri', 're', 'rang', 'chen', 'cheng', 'chang', 'chong', 'chuang')
}

_VI_VOWEL_TONES: dict[str, tuple[str, str, str, str, str]] = {
    'a': ('a', 'á', 'ả', 'à', 'ạ'),
    'ă': ('ă', 'ắ', 'ẳ', 'ằ', 'ặ'),
    'â': ('â', 'ấ', 'ẩ', 'ầ', 'ậ'),
    'e': ('e', 'é', 'ẻ', 'è', 'ẹ'),
    'ê': ('ê', 'ế', 'ể', 'ề', 'ệ'),
    'i': ('i', 'í', 'ỉ', 'ì', 'ị'),
    'o': ('o', 'ó', 'ỏ', 'ò', 'ọ'),
    'ô': ('ô', 'ố', 'ổ', 'ồ', 'ộ'),
    'ơ': ('ơ', 'ớ', 'ở', 'ờ', 'ợ'),
    'u': ('u', 'ú', 'ủ', 'ù', 'ụ'),
    'ư': ('ư', 'ứ', 'ử', 'ừ', 'ự'),
    'y': ('y', 'ý', 'ỷ', 'ỳ', 'ỵ'),
}

# High-frequency Chinese phrases & characters with exact Mandarin Pinyin (including tone sandhi)
_HANZI_PINYIN_DICT: dict[str, str] = {
    '你好吗': 'nǐ hǎo ma',
    '你好': 'nǐ hǎo',
    '您好': 'nín hǎo',
    '早上好': 'zǎoshang hǎo',
    '晚上好': 'wǎnshang hǎo',
    '下午好': 'xiàwǔ hǎo',
    '晚安': 'wǎn\'ān',
    '谢谢你': 'xièxie nǐ',
    '谢谢': 'xièxie',
    '多谢': 'duōxiè',
    '不客气': 'bú kèqi',
    '不用谢': 'bú yòng xiè',
    '对不起': 'duìbuqǐ',
    '不好意思': 'bù hǎo yìsi',
    '没关系': 'méi guānxi',
    '没事': 'méi shì',
    '再见': 'zàijiàn',
    '明天见': 'míngtiān jiàn',
    '回头见': 'huítóu jiàn',
    '我爱你': 'wǒ ài nǐ',
    '我喜欢你': 'wǒ xǐhuan nǐ',
    '我很好': 'wǒ hěn hǎo',
    '很高兴认识你': 'hěn gāoxìng rènshi nǐ',
    '你叫什么名字': 'nǐ jiào shénme míngzi',
    '我叫': 'wǒ jiào',
    '这是什么': 'zhè shì shénme',
    '那是什么': 'nà shì shénme',
    '我不知道': 'wǒ bù zhīdào',
    '我知道': 'wǒ zhīdào',
    '我明白': 'wǒ míngbai',
    '我不懂': 'wǒ bù dǒng',
    '今天天气怎么样': 'jīntiān tiānqì zěnmeyàng',
    '怎么样': 'zěnmeyàng',
    '为什么': 'wèishénme',
    '什么': 'shénme',
    '怎么': 'zěnme',
    '多少': 'duōshao',
    '多少钱': 'duōshao qián',
    '太贵了': 'tài guì le',
    '便宜': 'piányi',
    '好吃': 'hǎochī',
    '好喝': 'hǎohē',
    '好玩': 'hǎowán',
    '好看': 'hǎokàn',
    '吃饭': 'chīfàn',
    '喝水': 'hēshuǐ',
    '喜欢': 'xǐhuan',
    '学习': 'xuéxí',
    '中文': 'zhōngwén',
    '英文': 'yīngwén',
    '汉语': 'hànyǔ',
    '越南语': 'yuènányǔ',
    '越南': 'yuènán',
    '中国': 'zhōngguó',
    '美国': 'měiguó',
    '英国': 'yīngguó',
    '朋友': 'péngyou',
    '老师': 'lǎoshī',
    '学生': 'xuéshēng',
    '先生': 'xiānsheng',
    '小姐': 'xiǎojiě',
    '同学': 'tóngxué',
    '同事': 'tóngshì',
    '家人': 'jiārén',
    '爸爸': 'bàba',
    '妈妈': 'māma',
    '哥哥': 'gēge',
    '姐姐': 'jiějie',
    '弟弟': 'dìdi',
    '妹妹': 'mèimei',
    '今天': 'jīntiān',
    '明天': 'míngtiān',
    '昨天': 'zuótiān',
    '现在': 'xiànzài',
    '时候': 'shíhou',
    '时间': 'shíjiān',
    '地方': 'dìfang',
    '东西': 'dōngxi',
    '问题': 'wèntí',
    '工作': 'gōngzuò',
    '电脑': 'diànnǎo',
    '手机': 'shǒujī',
    '高兴': 'gāoxìng',
    '快乐': 'kuàilè',
    '幸福': 'xìngfú',
    '漂亮': 'piàoliang',
    '帅哥': 'shuàigē',
    '美女': 'měinǚ',
    '加油': 'jiāyóu',
    '没问题': 'méi wèntí',
    '真的吗': 'zhēnde ma',
    '当然': 'dāngrán',
    '可以': 'kěyǐ',
    '不可以': 'bù kěyǐ',
    '需要': 'xūyào',
    '帮忙': 'bāngmáng',
    '救命': 'jiùmìng',
    '恭喜发财': 'gōngxǐ fācái',
    '新年快乐': 'xīnnián kuàilè',
    '生日快乐': 'shēngrì kuàilè',
    '一路顺风': 'yílù shùnfēng',
    # Common single characters
    '我': 'wǒ', '你': 'nǐ', '您': 'nín', '他': 'tā', '她': 'tā', '它': 'tā', '们': 'men',
    '的': 'de', '是': 'shì', '不': 'bù', '了': 'le', '吗': 'ma', '呢': 'ne', '吧': 'ba', '啊': 'a',
    '在': 'zài', '有': 'yǒu', '没': 'méi', '和': 'hé', '跟': 'gēn', '也': 'yě', '都': 'dōu',
    '很': 'hěn', '太': 'tài', '真': 'zhēn', '最': 'zuì', '更': 'gèng', '非常': 'fēicháng',
    '好': 'hǎo', '大': 'dà', '小': 'xiǎo', '多': 'duō', '少': 'shǎo', '高': 'gāo', '低': 'dī',
    '长': 'cháng', '短': 'duǎn', '新': 'xīn', '旧': 'jiù', '快': 'kuài', '慢': 'màn',
    '冷': 'lěng', '热': 'rè', '贵': 'guì', '对': 'duì', '错': 'cuò',
    '来': 'lái', '去': 'qù', '回': 'huí', '到': 'dào', '走': 'zǒu', '跑': 'pǎo',
    '看': 'kàn', '听': 'tīng', '说': 'shuō', '读': 'dú', '写': 'xiě', '吃': 'chī', '喝': 'hē',
    '做': 'zuò', '买': 'mǎi', '卖': 'mài', '开': 'kāi', '关': 'guān', '找': 'zhǎo', '用': 'yòng',
    '想': 'xiǎng', '要': 'yào', '会': 'huì', '能': 'néng', '爱': 'ài', '叫': 'jiào', '请': 'qǐng',
    '问': 'wèn', '答': 'dá', '给': 'gěi', '送': 'sòng', '等': 'děng', '帮': 'bāng', '让': 'ràng',
    '人': 'rén', '家': 'jiā', '国': 'guó', '水': 'shuǐ', '火': 'huǒ', '山': 'shān', '天': 'tiān',
    '地': 'dì', '年': 'nián', '月': 'yuè', '日': 'rì', '号': 'hào', '点': 'diǎn', '分': 'fēn',
    '钱': 'qián', '车': 'chē', '路': 'lù', '门': 'mén', '书': 'shū', '字': 'zì', '话': 'huà',
    '上': 'shàng', '下': 'xià', '左': 'zuǒ', '右': 'yòu', '前': 'qián', '后': 'hòu', '里': 'lǐ', '外': 'wài',
    '一': 'yī', '二': 'èr', '两': 'liǎng', '三': 'sān', '四': 'sì', '五': 'wǔ',
    '六': 'liù', '七': 'qī', '八': 'bā', '九': 'jiǔ', '十': 'shí', '百': 'bǎi', '千': 'qiān', '万': 'wàn', '零': 'líng',
}
_SORTED_HANZI_KEYS = sorted(_HANZI_PINYIN_DICT.keys(), key=len, reverse=True)


def apply_vi_tone(syllable: str, mandarin_tone: int) -> str:
    """Apply Vietnamese tone mark corresponding to Mandarin tone 1..5.

    In Northern Vietnamese (Thái Sơn voice):
    - Tone 1 (55 high level)  -> ngang (0)
    - Tone 2 (35 rising)      -> sắc   (1)
    - Tone 3 (214 dipping)    -> hỏi   (2)
    - Tone 4 (51 high-falling)-> sắc   (1) (crisp high-pitch contour; huyền sounds flat/robotic)
    - Tone 5 (neutral/light)  -> ngang (0) or nặng (4)
    - Tone 6 (special light-falling for reduplicated 2nd syllable like xièxie) -> nặng (4)
    """
    tone_idx = {1: 0, 2: 1, 3: 2, 4: 1, 5: 0, 6: 4}.get(mandarin_tone, 0)
    if tone_idx == 0:
        return syllable
    for special in ('ê', 'ơ', 'ô', 'â', 'ă', 'ư'):
        idx = syllable.find(special)
        if idx != -1:
            return syllable[:idx] + _VI_VOWEL_TONES[special][tone_idx] + syllable[idx + 1:]
    start_search = 2 if syllable.startswith(('qu', 'gi')) and len(syllable) > 2 else 0
    vowels = [i for i in range(start_search, len(syllable)) if syllable[i] in _VI_VOWEL_TONES]
    if not vowels:
        vowels = [i for i in range(len(syllable)) if syllable[i] in _VI_VOWEL_TONES]
    if not vowels:
        return syllable
    if len(vowels) == 1:
        target = vowels[0]
    else:
        pair = syllable[vowels[0]:vowels[1] + 1]
        if pair in ('oa', 'oe', 'uy') or vowels[-1] < len(syllable) - 1:
            target = vowels[1]
        else:
            target = vowels[0]
    ch = syllable[target]
    return syllable[:target] + _VI_VOWEL_TONES[ch][tone_idx] + syllable[target + 1:]


def split_pinyin_initial_final(base_syl: str) -> tuple[str, str]:
    """Split a normalized ASCII Pinyin base syllable into (initial, final)."""
    s = base_syl.lower().replace('ü', 'v')
    for init in ('zh', 'ch', 'sh'):
        if s.startswith(init):
            return init, s[2:]
    if s and s[0] in 'bpmfdtnlgkhjqxrzcsyw':
        return s[0], s[1:]
    return '', s


def pinyin_syllable_to_vi(initial: str, final: str, tone: int) -> str:
    """Convert a Mandarin (initial, final, tone) into a Vietnamese-phonetic syllable."""
    if initial == 'y':
        if final == 'i':
            initial, final = '', 'i'
        elif final in ('u', 'v'):
            initial, final = '', 'v'
        elif final in ('ue', 've'):
            initial, final = '', 've'
        elif final in ('uan', 'van'):
            initial, final = '', 'van'
        elif final in ('un', 'vn'):
            initial, final = '', 'vn'
        elif final.startswith('i'):
            initial = ''
        else:
            initial, final = '', 'i' + final
    elif initial == 'w':
        if final == 'u':
            initial, final = '', 'u'
        elif final == 'o':
            initial, final = '', 'o'
        elif final.startswith('u'):
            initial = ''
        else:
            initial, final = '', 'u' + final

    if initial in ('j', 'q', 'x'):
        if final == 'u':
            final = 'v'
        elif final == 'ue':
            final = 've'
        elif final == 'uan':
            final = 'van'
        elif final == 'un':
            final = 'vn'

    if final == 'ui':
        final = 'uei'
    elif final == 'iu':
        final = 'iou'
    elif final == 'un':
        final = 'uen'

    if final == 'i' and initial in ('zh', 'ch', 'sh', 'r', 'z', 'c', 's'):
        final_vi = 'ư'
    else:
        final_map = {
            'a': 'a',
            'o': 'uô',
            'e': 'ơ',
            'ai': 'ai',
            'ei': 'ây',
            'ao': 'ao',
            'ou': 'âu',
            'an': 'an',
            'en': 'ân',
            'ang': 'ang',
            'eng': 'âng',
            'er': 'ơ',
            'ong': 'ung',
            'i': 'i',
            'ia': 'ia',
            'io': 'iô',
            'ie': 'ia',
            'iai': 'iai',
            'iao': 'iêu',
            'iou': 'iêu',
            'ian': 'iên',
            'in': 'in',
            'iang': 'iêng',
            'ing': 'inh',
            'iong': 'ung',
            'u': 'u',
            'ua': 'oa',
            'uo': 'ua',
            'uai': 'oai',
            'uei': 'uây',
            'uan': 'oan',
            'uen': 'uân',
            'uang': 'oang',
            'ueng': 'uâng',
            'v': 'uy',
            've': 'uê',
            'ue': 'uê',
            'van': 'uyên',
            'vn': 'uân',
        }
        if initial in ('b', 'p', 'm', 'f') and final == 'o':
            final_vi = 'ua'
        else:
            final_vi = final_map.get(final, final)

    init_map = {
        'b': 'p', 'p': 'ph', 'm': 'm', 'f': 'ph',
        'd': 't', 't': 'th', 'n': 'n', 'l': 'l',
        'g': 'c', 'k': 'kh', 'h': 'h',
        'j': 'ch', 'q': 'ch', 'x': 'x',
        'zh': 'tr', 'ch': 'tr', 'sh': 's', 'r': 'r',
        'z': 'ch', 'c': 'th', 's': 'x', '': '',
    }
    init_vi = init_map.get(initial, initial)
    if init_vi == 'h' and final in ('e', 'en', 'eng', 'u', 'ua', 'uo', 'uai', 'uei', 'uan', 'uen', 'uang'):
        init_vi = 'kh'
    if init_vi == 'c' and final_vi in ('oan', 'oang', 'oai', 'oa'):
        # Write 'quan', 'quang', 'quai', 'qua' for natural Vietnamese reading
        init_vi = 'qu'
        final_vi = 'a' + final_vi[2:]
    elif init_vi == 'c' and final_vi and final_vi[0] in ('i', 'e', 'ê', 'y'):
        init_vi = 'k'
    if init_vi == '' and final_vi.startswith('i') and len(final_vi) > 1:
        final_vi = 'y' + final_vi[1:]

    base = init_vi + final_vi
    en_homographs = {
        'i': 'y', 'u': 'u', 'an': 'an', 'in': 'in', 'on': 'ôn',
        'pan': 'ban', 'man': 'măn', 'tan': 'tăn', 'than': 'thăn', 'can': 'căn',
        'lung': 'lưng', 'loan': 'loăn', 'sang': 'xang', 'chao': 'trao',
        'pa': 'ba', 'pin': 'bin', 'thin': 'thin', 'sin': 'xin', 'win': 'uyn',
        'fan': 'phan', 'ban': 'băn', 'van': 'văn', 'ran': 'răn', 'lan': 'lăn',
    }
    if tone in (1, 5) and base in en_homographs:
        base = en_homographs[base]
    return apply_vi_tone(base, tone)


def _strip_pinyin_tones(word: str) -> tuple[str, list[tuple[int, int]]]:
    """Return (ascii_base, [(char_index, tone), ...]) for a Pinyin word."""
    norm = unicodedata.normalize('NFC', word.lower())
    chars: list[str] = []
    tones: list[tuple[int, int]] = []
    for idx, ch in enumerate(norm):
        if ch in _PINYIN_TONE_CHAR_MAP:
            base, t = _PINYIN_TONE_CHAR_MAP[ch]
            chars.append(base)
            tones.append((idx, t))
        else:
            chars.append(ch)
    return ''.join(chars), tones


def segment_pinyin_word(word: str) -> list[tuple[str, int]] | None:
    """Segment a single or multi-syllable Pinyin token into [(base_syllable, tone), ...]."""
    clean = word.strip("'\u2019-")
    if not clean:
        return None
    # Split on explicit apostrophes first (e.g., wǎn'ān -> ['wǎn', 'ān'])
    if "'" in clean or "\u2019" in clean:
        parts = [p for p in re.split(r"['\u2019]+", clean) if p]
        out: list[tuple[str, int]] = []
        for p in parts:
            sub = segment_pinyin_word(p)
            if not sub:
                return None
            out.extend(sub)
        return out

    norm = unicodedata.normalize('NFC', clean.lower())
    # Check if all characters are valid Pinyin letters
    base_chars: list[str] = []
    char_tones: list[int] = []
    for ch in norm:
        if ch in _PINYIN_TONE_CHAR_MAP:
            b, t = _PINYIN_TONE_CHAR_MAP[ch]
            base_chars.append(b)
            char_tones.append(t)
        elif 'a' <= ch <= 'z':
            base_chars.append(ch)
            char_tones.append(0)
        else:
            return None
    base_str = ''.join(base_chars)

    # Backtracking segmentation into _VALID_PINYIN_SYLLABLES
    n = len(base_str)

    @functools.lru_cache(maxsize=None)
    def _solve(pos: int) -> list[tuple[str, int]] | None:
        if pos == n:
            return []
        # Try longest syllable first (max length 6: zhuang, chuang, shuang)
        for end in range(min(n, pos + 6), pos, -1):
            cand = base_str[pos:end]
            # Without an explicit apostrophe, a subsequent syllable (pos > 0) must start with a consonant
            if pos > 0 and cand[0] in 'aeiouv':
                continue
            if cand in _VALID_PINYIN_SYLLABLES:
                tones_in_span = [t for t in char_tones[pos:end] if t > 0]
                if len(tones_in_span) > 1:
                    continue  # A single syllable cannot have 2 tone marks
                rest = _solve(end)
                if rest is not None:
                    tone = tones_in_span[0] if tones_in_span else 5
                    return [(cand, tone), *rest]
        return None

    return _solve(0)


def is_unmistakable_pinyin_token(token: str) -> bool:
    """Return True if token is definitely Mandarin Pinyin (and not Vietnamese or English)."""
    norm = unicodedata.normalize('NFC', token)
    if any(ch in _STRICT_PINYIN_CHARS for ch in norm):
        return segment_pinyin_word(norm) is not None
    # Check if it has acute/grave accents and segments into Pinyin
    has_diacritic = any(ord(ch) > 127 for ch in norm)
    if not has_diacritic:
        return False
    # If it contains Vietnamese-exclusive letters (ă, â, đ, ê, ô, ơ, ư, ả, ã, ạ, etc.), it's Vietnamese
    if any(ch not in _PINYIN_TONE_CHAR_MAP and not ('a' <= ch.lower() <= 'z') and ch not in "'\u2019"
           for ch in norm):
        return False
    segs = segment_pinyin_word(norm)
    if not segs:
        return False
    # Multi-syllable accented word (e.g., xièxie, zàijiàn, míngzi, rènshi) is definitely Pinyin
    if len(segs) >= 2:
        return True
    # Single syllable with acute/grave: only treat as unmistakable Pinyin if base is non-Vietnamese
    base_syl, _ = segs[0]
    return base_syl in _NON_VI_PINYIN_BASES


def _convert_pinyin_syllable_list_to_vi(syls: list[tuple[str, int]]) -> list[str]:
    """Convert a sequence of (base_syllable, tone) with cross-syllable sandhi into Vietnamese phonetics."""
    if not syls:
        return []
    adjusted = list(syls)
    # Apply Mandarin third-tone sandhi across the entire sequence: 3 + 3 -> 2 + 3
    for i in range(len(adjusted) - 1):
        if adjusted[i][1] == 3 and adjusted[i + 1][1] == 3:
            adjusted[i] = (adjusted[i][0], 2)
    # Reduplicated Tone-4 + neutral/Tone-4 (e.g. xièxie, bàba, mèimei, dìdi) -> 4 + 6 (light falling)
    for i in range(len(adjusted) - 1):
        if (adjusted[i][0] == adjusted[i + 1][0]
                and adjusted[i][1] == 4 and adjusted[i + 1][1] in (4, 5)):
            adjusted[i + 1] = (adjusted[i + 1][0], 6)
    out = []
    for base_syl, tone in adjusted:
        init, fin = split_pinyin_initial_final(base_syl)
        out.append(pinyin_syllable_to_vi(init, fin, tone))
    return out


def convert_pinyin_token_to_vi(token: str) -> str:
    """Convert a segmented Pinyin token into space-separated Vietnamese-phonetic syllables."""
    segs = segment_pinyin_word(token)
    if not segs:
        return token
    return ' '.join(_convert_pinyin_syllable_list_to_vi(segs))


# ── 2. Hanzi Conversion (Dictionary + Offline espeakbridge cmn Fallback) ────

_ESPEAK_LOCK = threading.Lock()
_ESPEAK_READY = False
_ESPEAK_UNAVAILABLE = False

_ESPEAK_SYL_RE = re.compile(
    r"(?P<init>ts\.h|ts\.|tɕh|tɕj|tɕ|tsh|ts|s\.w|s\.|ph|th|kh|kw|[ptkmfnlɕsʐχwj])?"
    r"(?P<vowel>[ɑaəeioyɛu.\-̪]+(?:nɡ)?)"
    r"(?P<tone>[12ɜ5])"
    r"(?P<coda>(?:nɡ|ŋ|n)(?![ɑaəeioyɛu]))?"
)

_ESPEAK_INIT_TO_PINYIN = {
    'ts.h': 'ch', 'ts.': 'zh', 's.w': 'sh', 's.': 'sh',
    'tɕh': 'q', 'tɕj': 'j', 'tɕ': 'j', 'ɕ': 'x',
    'tsh': 'c', 'ts': 'z', 's': 's', 'ʐ': 'r',
    'ph': 'p', 'p': 'b', 'th': 't', 't': 'd',
    'kh': 'k', 'kw': 'g', 'k': 'g', 'χ': 'h',
    'm': 'm', 'f': 'f', 'n': 'n', 'l': 'l',
    'w': 'w', 'j': 'y', '': '',
}


def _get_espeak_bridge():
    """Lazily load piper.espeakbridge from current env or sibling .venv."""
    global _ESPEAK_READY, _ESPEAK_UNAVAILABLE
    if _ESPEAK_UNAVAILABLE:
        return None
    try:
        from piper import espeakbridge
        from piper.phonemize_espeak import ESPEAK_DATA_DIR
    except ImportError:
        root = Path(__file__).resolve().parent.parent
        venv_site = root / '.venv' / 'Lib' / 'site-packages'
        if venv_site.is_dir() and str(venv_site) not in sys.path:
            sys.path.append(str(venv_site))
        try:
            from piper import espeakbridge
            from piper.phonemize_espeak import ESPEAK_DATA_DIR
        except ImportError:
            _ESPEAK_UNAVAILABLE = True
            return None

    if not _ESPEAK_READY:
        data_path = str(ESPEAK_DATA_DIR)
        if os.name == 'nt' and not data_path.isascii():
            buf = ctypes.create_unicode_buffer(32768)
            length = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW(
                data_path, buf, len(buf)
            )
            if 0 < length < len(buf):
                data_path = buf.value
        try:
            espeakbridge.initialize(data_path)
            _ESPEAK_READY = True
        except Exception:
            _ESPEAK_UNAVAILABLE = True
            return None
    return espeakbridge


def _espeak_hanzi_to_vi(hanzi: str) -> str:
    """Convert any CJK Hanzi string via offline espeakbridge cmn into Vietnamese phonetics."""
    bridge = _get_espeak_bridge()
    if bridge is None:
        return ''
    with _ESPEAK_LOCK:
        try:
            bridge.set_voice('cmn')
            clauses = bridge.get_phonemes(hanzi)
        except Exception:
            return ''
        finally:
            try:
                bridge.set_voice('vi')
            except Exception:
                pass
    out_words: list[str] = []
    for ph_str, _term, _eos in clauses:
        clean = re.sub(r'[ˈˌ]', '', ph_str)
        for token in clean.split():
            for m in _ESPEAK_SYL_RE.finditer(token):
                init_raw = m.group('init') or ''
                v_raw = m.group('vowel') or ''
                tone_raw = m.group('tone')
                coda_raw = m.group('coda') or ''
                init = _ESPEAK_INIT_TO_PINYIN.get(init_raw, '')
                if init_raw in ('kw', 's.w') and not v_raw.startswith(('u', 'w')):
                    v_raw = 'u' + v_raw
                elif init_raw == 'tɕj' and not v_raw.startswith(('i', 'j')):
                    v_raw = 'i' + v_raw
                if v_raw.startswith('w'):
                    v_raw = 'u' + v_raw[1:]
                elif v_raw.startswith('j'):
                    v_raw = 'i' + v_raw[1:]
                if v_raw in ('i.', 'i̪'):
                    final = 'i'
                elif v_raw == 'o-':
                    final = 'e'
                elif v_raw == 'onɡ' or (v_raw == 'o' and coda_raw in ('nɡ', 'ŋ')):
                    final = 'ong'
                    coda_raw = ''
                else:
                    v_map = {
                        'ɑu': 'ao', 'au': 'ao', 'uɑu': 'uao', 'iɑu': 'iao',
                        'ɑ': 'a', 'a': 'a', 'uɑ': 'ua', 'iɑ': 'ia',
                        'iɛ': 'ie', 'yɛ': 've', 'y': 'v',
                        'ei': 'ei', 'ai': 'ai', 'uai': 'uai',
                        'iou': 'iu', 'ou': 'ou',
                        'uei': 'ui', 'uo': 'uo', 'ua': 'ua',
                        'uə': 'u', 'ə': 'e', 'i': 'i', 'u': 'u', 'o': 'o',
                    }
                    base_v = v_map.get(
                        v_raw,
                        v_raw.replace('ɑ', 'a').replace('ɛ', 'e').replace('ə', 'e'),
                    )
                    if coda_raw in ('nɡ', 'ŋ'):
                        final = ('eng' if base_v == 'e' else 'ing' if base_v == 'i'
                                 else 'ung' if base_v == 'u' else base_v + 'ng')
                    elif coda_raw == 'n':
                        final = ('en' if base_v == 'e' else 'in' if base_v == 'i'
                                 else 'un' if base_v == 'u' else base_v + 'n')
                    else:
                        final = base_v
                tone = {'5': 1, 'ɜ': 2, '2': 3, '1': 5}.get(tone_raw, 1)
                out_words.append(pinyin_syllable_to_vi(init, final, tone))
    return ' '.join(out_words)


def convert_hanzi_span_to_vi(hanzi: str) -> str:
    """Convert a span of CJK Hanzi characters into Vietnamese-phonetic Mandarin with phrase-level sandhi."""
    i = 0
    n = len(hanzi)
    out: list[str] = []
    known_syls: list[tuple[str, int]] = []
    unknown_buf: list[str] = []

    def _flush_known() -> None:
        if not known_syls:
            return
        out.append(' '.join(_convert_pinyin_syllable_list_to_vi(known_syls)))
        known_syls.clear()

    def _flush_unknown() -> None:
        if not unknown_buf:
            return
        _flush_known()
        chunk = ''.join(unknown_buf)
        unknown_buf.clear()
        converted = _espeak_hanzi_to_vi(chunk)
        if converted:
            out.append(converted)

    while i < n:
        matched = False
        for key in _SORTED_HANZI_KEYS:
            if hanzi.startswith(key, i):
                _flush_unknown()
                py_phrase = _HANZI_PINYIN_DICT[key]
                for tok in py_phrase.split():
                    segs = segment_pinyin_word(tok)
                    if segs:
                        known_syls.extend(segs)
                i += len(key)
                matched = True
                break
        if not matched:
            unknown_buf.append(hanzi[i])
            i += 1
    _flush_unknown()
    _flush_known()
    return ' '.join(out)


# ── 3. Hanzi/Pinyin Deduplication & Full Sentence Preprocessing ────────────

# Pattern 1: Hanzi followed by (Pinyin) or （Pinyin） or [Pinyin]
_HANZI_WITH_PAREN_RE = re.compile(
    r'(?P<hanzi>[\u4e00-\u9fff]+)\s*[\(\uff08\[](?P<inner>[^)\uff09\]]+)[\)\uff09\]]'
)
# Pattern 2: Pinyin (quoted or unquoted) followed by (Hanzi) or （Hanzi）
_PAREN_HANZI_AFTER_PINYIN_RE = re.compile(
    r'(?P<pre>["\'\u201c\u2018]?[A-Za-z\u00c0-\u024f\u1e00-\u1eff\'\u2019\s,!?.\-]+["\'\u201d\u2019]?)'
    r'\s*[\(\uff08\[][\u4e00-\u9fff\s,，。！？!?.]+[\)\uff09\]]'
)


def _deduplicate_hanzi_pinyin(text: str) -> str:
    """Avoid speaking both Hanzi and its parenthetical Pinyin (or vice versa) twice."""
    def _replace_hanzi_paren(match: re.Match) -> str:
        hanzi = match.group('hanzi')
        inner = match.group('inner').strip()
        # Check if inner looks like Pinyin (words that segment as Pinyin)
        words = re.findall(r"[A-Za-z\u00c0-\u024f\'\u2019]+", inner)
        if words and all(segment_pinyin_word(w) is not None for w in words):
            # If inner has explicit tone marks, use inner Pinyin; else use Hanzi conversion
            if any(any(ord(c) > 127 for c in unicodedata.normalize('NFC', w)) for w in words):
                return inner
            return hanzi
        return match.group(0)

    text = _HANZI_WITH_PAREN_RE.sub(_replace_hanzi_paren, text)

    def _replace_pinyin_paren_hanzi(match: re.Match) -> str:
        pre = match.group('pre')
        words = re.findall(r"[A-Za-z\u00c0-\u024f\'\u2019]+", pre)
        if words and any(is_unmistakable_pinyin_token(w) for w in words):
            return pre
        return match.group(0)

    return _PAREN_HANZI_AFTER_PINYIN_RE.sub(_replace_pinyin_paren_hanzi, text)


_WORD_TOKEN_RE = re.compile(r"[A-Za-z\u00c0-\u024f\u1e00-\u1eff]+(?:['\u2019][A-Za-z\u00c0-\u024f\u1e00-\u1eff]+)*")

# Single-syllable words that are valid Pinyin when in a Pinyin phrase
_CONTEXTUAL_PINYIN_WORDS = {
    'ai', 'bu', 'da', 'de', 'dui', 'gui', 'hao', 'hen', 'hui', 'kan', 'ke',
    'le', 'ma', 'mei', 'men', 'ne', 'neng', 'ni', 'nin', 'ren', 'shi',
    'ta', 'tai', 'wo', 'xie',
}


def _convert_pinyin_spans(text: str) -> str:
    """Find unmistakable Pinyin tokens (and their Pinyin phrase neighbors) and convert to Vietnamese phonetics."""
    matches = list(_WORD_TOKEN_RE.finditer(text))
    if not matches:
        return text
    n = len(matches)
    is_py = [is_unmistakable_pinyin_token(m.group(0)) for m in matches]
    if not any(is_py):
        return text

    # Propagate Pinyin status to adjacent contextual Pinyin words within the same Pinyin phrase
    changed = True
    while changed:
        changed = False
        for i in range(n):
            if is_py[i]:
                continue
            tok = matches[i].group(0)
            norm = unicodedata.normalize('NFC', tok)
            if any(ch not in _PINYIN_TONE_CHAR_MAP and not ('a' <= ch.lower() <= 'z') and ch not in "'\u2019"
                   for ch in norm):
                continue
            segs = segment_pinyin_word(norm)
            if not segs:
                continue
            base_syl, tone = segs[0]
            if len(segs) == 1 and base_syl not in _CONTEXTUAL_PINYIN_WORDS and base_syl not in _NON_VI_PINYIN_BASES:
                continue
            # Check if strictly adjacent (only spaces, no commas/punctuation) to a Pinyin word
            left_space_only = (i > 0 and is_py[i - 1]
                               and text[matches[i - 1].end():matches[i].start()] == ' ')
            right_space_only = (i + 1 < n and is_py[i + 1]
                                and text[matches[i].end():matches[i + 1].start()] == ' ')
            # Unmarked neutral particles (ma, ne, le, de, men) only attach after a Pinyin word before punctuation/end
            if tone == 5:
                after_text = text[matches[i].end():].lstrip()
                if left_space_only and base_syl in ('ma', 'ne', 'le', 'de', 'men') and (
                    not after_text or after_text[0] in '?!.,;)"\'\u201d\u2019' or right_space_only
                ):
                    is_py[i] = True
                    changed = True
            else:
                # Accented contextual Pinyin words (ài, bù, bú, kè, guì, tài):
                # attach if between two Pinyin words, or immediately before a Pinyin word (e.g. Bù kèqì, Tài guì)
                if (left_space_only and right_space_only) or (
                    right_space_only and base_syl in ('bu', 'tai', 'hen', 'mei', 'dui', 'wo', 'ni', 'ta')
                ) or (
                    left_space_only and base_syl in ('ai', 'ke', 'gui', 'hao', 'ni', 'wo', 'ta')
                ):
                    is_py[i] = True
                    changed = True

    out: list[str] = []
    last = 0
    i = 0
    while i < n:
        m = matches[i]
        out.append(text[last:m.start()])
        if is_py[i]:
            # Group contiguous space-separated Pinyin tokens so 3+3 tone sandhi applies across words
            j = i
            phrase_syls: list[tuple[str, int]] = []
            while True:
                segs = segment_pinyin_word(matches[j].group(0))
                if segs:
                    phrase_syls.extend(segs)
                if (j + 1 < n and is_py[j + 1]
                        and text[matches[j].end():matches[j + 1].start()] == ' '):
                    j += 1
                else:
                    break
            out.append(' '.join(_convert_pinyin_syllable_list_to_vi(phrase_syls)))
            last = matches[j].end()
            i = j + 1
        else:
            out.append(m.group(0))
            last = m.end()
            i += 1
    out.append(text[last:])
    return ''.join(out)


# ── 4. English Preprocessing & VieNeu <en> Tagger ──────────────────────────

# IPA characters that only appear inside phonetic transcriptions /.../
_IPA_SLASH_RE = re.compile(
    r'(?:,?\s*(?:có\s+)?(?:phát\s+âm|phiên\s+âm(?:\s+quốc\s+tế)?|đọc)\s+(?:là\s+)?)?'
    r'[\(\[]?\s*/(?=[^/\n]*[əˈˌɪʊʌæɑɔɜɚɝθðʃʒŋɹːɡɐᵻ])[^/\n]{1,60}/\s*[\)\]]?',
    flags=re.IGNORECASE,
)

# Technical acronyms that should be spelled out in English letters (<en>u r l</en>)
_EN_ACRONYMS: set[str] = {
    'AI', 'API', 'UI', 'UX', 'URL', 'URI', 'HTTP', 'HTTPS', 'HTML', 'CSS', 'SQL',
    'CPU', 'GPU', 'APU', 'TPU', 'NPU', 'SSD', 'HDD', 'USB', 'PDF', 'CEO', 'CTO', 'CFO',
    'PC', 'OK', 'ID', 'IP', 'OS', 'IT', 'PR', 'HR', 'QA', 'QC', 'STT', 'TTS', 'LLM', 'MCP',
    'DNS', 'VPN', 'SSH', 'FTP', 'TCP', 'UDP', 'SDK', 'IDE', 'CLI', 'GUI', 'JWT', 'DOM',
    'XML', 'CSV', 'PNG', 'JPG', 'GIF', 'MP3', 'MP4', 'WAV', 'FPS', 'RGB', 'LED', 'LCD',
    'HDMI', 'VRAM',
}

# English words that look like valid Vietnamese syllables and need <en>...</en> when used as English
_AMBIGUOUS_EN_WORDS: set[str] = {
    'a', 'ah', 'am', 'an', 'as', 'at', 'be', 'by', 'do', 'go', 'he', 'hi', 'i', 'if', 'in', 'is', 'it',
    'me', 'my', 'no', 'of', 'oh', 'ok', 'on', 'or', 'so', 'to', 'up', 'us', 'we',
    'ban', 'can', 'con', 'dan', 'don', 'fan', 'han', 'lan', 'man', 'men', 'pan', 'pin',
    'ran', 'sin', 'son', 'sun', 'tan', 'tin', 'ton', 'van', 'win',
    'bad', 'bag', 'bat', 'bed', 'bet', 'big', 'bit', 'box', 'bus', 'but', 'buy',
    'car', 'cat', 'cup', 'cut', 'dad', 'day', 'did', 'dog', 'dry',
    'ear', 'eat', 'egg', 'end', 'eye', 'far', 'fat', 'few', 'fit', 'fix', 'fly', 'for', 'fun',
    'get', 'gas', 'got', 'gun', 'guy', 'gym', 'had', 'has', 'hat', 'her', 'him', 'his', 'hit', 'hot', 'how',
    'ice', 'ill', 'its', 'job', 'joy', 'key', 'kid', 'kit', 'lab', 'law', 'lay', 'led', 'leg', 'let',
    'lie', 'lip', 'log', 'lot', 'low', 'mad', 'map', 'may', 'met', 'mix', 'mom', 'mud',
    'net', 'new', 'nor', 'not', 'now', 'nut', 'odd', 'off', 'oil', 'old', 'one', 'our', 'out', 'own',
    'pay', 'pen', 'pet', 'pie', 'pig', 'pop', 'pot', 'put', 'raw', 'red', 'rid', 'row', 'run',
    'sad', 'sat', 'saw', 'say', 'sea', 'see', 'set', 'she', 'shy', 'sir', 'sit', 'six', 'sky',
    'sum', 'tax', 'tea', 'ten', 'the', 'tie', 'tip', 'top', 'toy', 'try', 'two',
    'use', 'via', 'war', 'was', 'way', 'web', 'wet', 'who', 'why', 'won', 'yes', 'yet', 'you', 'zoo',
}

# Unmistakable common English words (never valid Vietnamese words) used to detect English context
_UNMISTAKABLE_EN_WORDS: set[str] = {
    'about', 'above', 'across', 'after', 'again', 'against', 'almost', 'alone', 'along', 'already',
    'also', 'although', 'always', 'among', 'another', 'answer', 'any', 'anything', 'anyway', 'anywhere',
    'apple', 'are', 'aren', 'around', 'ask', 'assistant', 'available', 'away',
    'baby', 'back', 'beautiful', 'because', 'become', 'been', 'before', 'begin', 'behind', 'believe',
    'below', 'best', 'better', 'between', 'beyond', 'black', 'blue', 'board', 'body', 'book', 'both',
    'bring', 'brother', 'build', 'business', 'call', 'called', 'came', 'cannot', 'care', 'carry',
    'catch', 'cause', 'center', 'certain', 'change', 'check', 'child', 'children', 'chinese', 'choice',
    'choose', 'chrome', 'city', 'class', 'clean', 'clear', 'click', 'close', 'coffee', 'cold', 'college',
    'color', 'come', 'coming', 'common', 'company', 'complete', 'computer', 'control', 'cool', 'copy',
    'correct', 'cost', 'costs', 'could', 'couldn', 'country', 'course', 'Học', 'create', 'current',
    'dark', 'data', 'date', 'daughter', 'dead', 'deal', 'dear', 'deep', 'desktop', 'develop',
    'different', 'difficult', 'dinner', 'direct', 'discord', 'doctor', 'does', 'doesn', 'doing',
    'dollar', 'dollars', 'done', 'door', 'down', 'draw', 'dream', 'drink', 'drive', 'drop', 'during',
    'each', 'early', 'earth', 'easy', 'education', 'effect', 'eight', 'either', 'else', 'email',
    'english', 'enjoy', 'enough', 'enter', 'even', 'evening', 'event', 'ever', 'every', 'everybody',
    'everyone', 'everything', 'example', 'excited', 'excuse', 'experience', 'explain',
    'face', 'facebook', 'fact', 'fail', 'fall', 'false', 'family', 'fast', 'father', 'favorite',
    'feel', 'feeling', 'field', 'fight', 'figure', 'file', 'fill', 'final', 'finally', 'find', 'fine',
    'finger', 'finish', 'fire', 'first', 'fish', 'five', 'floor', 'flower', 'focus', 'folder', 'follow',
    'food', 'foot', 'force', 'foreign', 'forget', 'form', 'four', 'free', 'friend', 'friends', 'from',
    'front', 'full', 'future', 'game', 'games', 'garden', 'gave', 'general', 'getting', 'girl', 'give',
    'given', 'glad', 'glass', 'gmail', 'going', 'gold', 'gone', 'good', 'goodbye', 'google', 'great',
    'green', 'ground', 'group', 'grow', 'guess', 'hair', 'half', 'hall', 'hand', 'happen', 'happy',
    'hard', 'have', 'haven', 'having', 'head', 'health', 'hear', 'heard', 'heart', 'heavy', 'hello',
    'help', 'here', 'high', 'history', 'hold', 'home', 'hope', 'horse', 'hospital', 'hotel', 'hour',
    'hours', 'house', 'however', 'huge', 'human', 'hundred', 'idea', 'image', 'important', 'include',
    'information', 'inside', 'instead', 'interest', 'interesting', 'internet', 'into', 'issue',
    'join', 'just', 'keep', 'kind', 'king', 'kitchen', 'knew', 'know', 'knowledge', 'known',
    'land', 'language', 'large', 'last', 'late', 'later', 'laugh', 'laptop', 'lead', 'learn', 'learning',
    'least', 'leave', 'left', 'less', 'letter', 'level', 'life', 'light', 'like', 'likely', 'line',
    'link', 'list', 'listen', 'listening', 'little', 'live', 'living', 'local', 'long', 'look', 'looking',
    'lose', 'lost', 'love', 'lovely', 'luck', 'lucky', 'lunch', 'machine', 'made', 'main', 'major',
    'make', 'making', 'many', 'market', 'matter', 'maybe', 'mean', 'meaning', 'measure', 'meat',
    'media', 'medical', 'meet', 'meeting', 'member', 'memory', 'message', 'messenger', 'middle', 'might',
    'mile', 'milk', 'million', 'mind', 'mine', 'minecraft', 'minute', 'minutes', 'miss', 'mistake',
    'model', 'modern', 'moment', 'money', 'month', 'months', 'moon', 'more', 'morning', 'most', 'mother',
    'mountain', 'mouse', 'mouth', 'move', 'movie', 'movies', 'much', 'music', 'must', 'myself',
    'name', 'national', 'natural', 'nature', 'near', 'nearly', 'necessary', 'need', 'network', 'never',
    'news', 'next', 'nice', 'night', 'nine', 'nobody', 'none', 'normal', 'north', 'note', 'nothing',
    'notice', 'number', 'object', 'office', 'often', 'okay', 'once', 'online', 'only', 'open', 'option',
    'orange', 'order', 'other', 'others', 'outside', 'over', 'page', 'pain', 'paint', 'pair', 'paper',
    'parent', 'parents', 'park', 'part', 'party', 'pass', 'past', 'peace', 'people', 'Lịch', 'perfect',
    'perhaps', 'period', 'person', 'personal', 'phone', 'photo', 'pick', 'picture', 'piece', 'place',
    'plan', 'plant', 'play', 'playing', 'player', 'please', 'point', 'police', 'policy', 'poor',
    'popular', 'position', 'possible', 'power', 'practice', 'prepare', 'present', 'president', 'press',
    'pretty', 'price', 'private', 'probably', 'problem', 'process', 'produce', 'product', 'program',
    'project', 'protect', 'prove', 'provide', 'public', 'pull', 'purpose', 'push', 'python',
    'quality', 'question', 'quick', 'quickly', 'quiet', 'quite', 'radio', 'rain', 'raise', 'reach',
    'read', 'reading', 'ready', 'real', 'realize', 'really', 'reason', 'receive', 'recent', 'record',
    'reduce', 'remember', 'remove', 'repeat', 'Part', 'reply', 'report', 'require', 'research', 'resource',
    'respond', 'response', 'rest', 'result', 'return', 'review', 'rich', 'ride', 'right', 'ring', 'rise',
    'FPT', 'river', 'road', 'rock', 'role', 'room', 'round', 'rule', 'running', 'safe', 'said', 'same',
    'save', 'school', 'science', 'screen', 'search', 'season', 'seat', 'second', 'secret', 'section',
    'security', 'seem', 'seen', 'select', 'self', 'sell', 'send', 'sense', 'sent', 'sentence', 'series',
    'serious', 'serve', 'service', 'seven', 'several', 'shake', 'shall', 'shape', 'share', 'short',
    'should', 'shouldn', 'shoulder', 'show', 'shut', 'sick', 'side', 'sign', 'simple', 'since', 'sing',
    'single', 'sister', 'site', 'situation', 'size', 'skill', 'skin', 'sleep', 'slow', 'small', 'ach',
    'smart', 'smile', 'snow', 'social', 'software', 'some', 'somebody', 'someone', 'something',
    'sometimes', 'somewhere', 'song', 'soon', 'sorry', 'sort', 'sound', 'south', 'space', 'speak',
    'speaking', 'special', 'spend', 'sport', 'spotify', 'spring', 'staff', 'stage', 'stand', 'standard',
    'star', 'start', 'state', 'station', 'stay', 'step', 'still', 'stock', 'stop', 'store', 'story',
    'straight', 'strange', 'street', 'strong', 'student', 'study', 'stuff', 'style', 'subject',
    'success', 'successful', 'such', 'sudden', 'suddenly', 'suggest', 'summer', 'support', 'sure',
    'surface', 'system', 'table', 'take', 'taken', 'talk', 'talking', 'tall', 'task', 'teach', 'teacher',
    'team', 'technology', 'tell', 'temperature', 'term', 'test', 'text', 'than', 'thank', 'thanks',
    'that', 'their', 'them', 'themselves', 'then', 'there', 'therefore', 'these', 'they', 'thing',
    'things', 'think', 'thinking', 'third', 'this', 'those', 'though', 'thought', 'thousand', 'three',
    'through', 'throw', 'tiktok', 'time', 'times', 'tired', 'today', 'together', 'told', 'tomorrow',
    'tonight', 'took', 'tool', 'total', 'touch', 'toward', 'town', 'trade', 'training', 'travel', 'tree',
    'trip', 'trouble', 'true', 'truth', 'turn', 'twenty', 'type', 'under', 'understand', 'unit', 'until',
    'upon', 'usual', 'usually', 'value', 'various', 'very', 'video', 'view', 'vietnam', 'vietnamese',
    'village', 'virtual', 'visit', 'voice', 'wait', 'waiting', 'walk', 'wall', 'want', 'warm', 'wash',
    'watch', 'watching', 'water', 'wear', 'weather', 'website', 'week', 'weekend', 'weight', 'welcome',
    'well', 'went', 'were', 'weren', 'west', 'what', 'whatever', 'when', 'where', 'whether', 'which',
    'while', 'white', 'whole', 'whom', 'whose', 'wide', 'wife', 'will', 'wind', 'window', 'windows',
    'wish', 'with', 'within', 'without', 'woman', 'women', 'wonder', 'wonderful', 'wood', 'word',
    'words', 'work', 'working', 'world', 'worry', 'worse', 'worst', 'worth', 'would', 'wouldn', 'write',
    'writing', 'wrong', 'yeah', 'year', 'years', 'yellow', 'yesterday', 'young', 'your', 'yourself',
    'youtube',
}
_ALL_KNOWN_EN_WORDS = (_AMBIGUOUS_EN_WORDS | _UNMISTAKABLE_EN_WORDS) - {'Học', 'Lịch', 'Part', 'FPT', 'ach'}


def _normalize_uppercase_english_words(text: str) -> str:
    """Lowercase ALL-CAPS English words (like HELLO, LOVE, YOU) while keeping acronyms (AI, URL, PDF)."""
    def _repl(match: re.Match) -> str:
        word = match.group(0)
        if word in _EN_ACRONYMS:
            return word
        low = word.lower()
        if low in _ALL_KNOWN_EN_WORDS and len(word) >= 2:
            return low
        return word

    return re.sub(r'\b[A-Z]{2,}\b', _repl, text)


def _smart_replace_name(text: str, name: str, spoken_name: str) -> str:
    """Replace 'Alex' with 'A lếch' in Vietnamese spans, but keep 'Alex' inside English sentences."""
    if not name or name.lower() == spoken_name.lower():
        return text
    pattern = re.compile(rf'\b{re.escape(name)}\b', flags=re.IGNORECASE)

    def _repl(match: re.Match) -> str:
        before = text[:match.start()]
        after = text[match.end():]
        prev_words = re.findall(r"[A-Za-z\u00c0-\u024f\u1e00-\u1eff']+", before)[-2:]
        next_words = re.findall(r"[A-Za-z\u00c0-\u024f\u1e00-\u1eff']+", after)[:2]
        neighbors = [w.lower().strip("'") for w in (*prev_words, *next_words)]
        if any(w in _UNMISTAKABLE_EN_WORDS or w in ("i'm", "is", "am", "hi", "hello", "hey", "call")
               for w in neighbors):
            return name
        return spoken_name

    return pattern.sub(_repl, text)


def prepare_multilang_speech(text: str, name: str = 'Alex', spoken_name: str = 'A lếch') -> str:
    """Clean and normalize Vietnamese + English + Chinese text for TTS synthesis."""
    if not text:
        return ''
    # 1. Normalize curly apostrophes inside words (I’m -> I'm, Wǎn’ān -> Wǎn'ān)
    text = re.sub(r'(?<=\w)[\u2018\u2019`](?=\w)', "'", text)
    # 2. Strip inline IPA phonetic transcriptions like /həˈloʊ/
    text = _IPA_SLASH_RE.sub('', text)
    # 3. Deduplicate Hanzi (Pinyin) or Pinyin (Hanzi) pairs
    text = _deduplicate_hanzi_pinyin(text)
    # 4. Convert all CJK Hanzi spans [\u4e00-\u9fff]+ into Vietnamese-phonetic Mandarin
    text = re.sub(r'[\u4e00-\u9fff]+', lambda m: ' ' + convert_hanzi_span_to_vi(m.group(0)) + ' ', text)
    # 5. Convert Pinyin words/phrases into Vietnamese-phonetic Mandarin
    text = _convert_pinyin_spans(text)
    # 6. Normalize CJK punctuation into standard ASCII punctuation with spacing
    cjk_punc = {
        '。': '. ', '！': '! ', '？': '? ', '；': '; ',
        '，': ', ', '：': ': ', '、': ', ',
        '（': ' (', '）': ') ', '【': ' [', '】': '] ',
        '「': ' "', '」': '" ', '『': ' "', '』': '" ',
        '“': '"', '”': '"',
    }
    for k, v in cjk_punc.items():
        if k in text:
            text = text.replace(k, v)
    # 7. Lowercase ALL-CAPS English words (LOVE -> love) while keeping technical acronyms (URL, PDF)
    text = _normalize_uppercase_english_words(text)
    # 8. Replace assistant name smartly (A lếch in Vietnamese, Alex in English)
    if name and spoken_name:
        text = _smart_replace_name(text, name, spoken_name)
    text = re.sub(r'\s+', ' ', text).strip()
    return re.sub(r'\s+([,.!?;:\)\]])', r'\1', text)


#Quoted span regex for VieNeu <en> tagging
_QUOTED_SPAN_RE = re.compile(r'(["\'])(?P<inner>[A-Za-z][A-Za-z0-9\'\s,\-!?]{0,80}?)\1')


def tag_english_for_vieneu(text: str) -> str:
    """Wrap ambiguous English words, quoted English phrases, and acronyms in <en>...</en> for VieNeu."""
    if not text:
        return ''

    # 1. Wrap quoted ASCII English words/phrases (e.g., "go", "do", "I am") in <en>...</en>
    def _quote_repl(match: re.Match) -> str:
        inner = match.group('inner').strip()
        words = [w.lower().strip("'-") for w in re.findall(r"[A-Za-z']+", inner)]
        if words and all(w in _ALL_KNOWN_EN_WORDS or w.upper() in _EN_ACRONYMS for w in words):
            return f'<en>{inner.lower()}</en>'
        return match.group(0)

    text = _QUOTED_SPAN_RE.sub(_quote_repl, text)

    # 2. Convert technical acronyms (URL, PDF, HTTPS, STT, etc.) outside <en> into <en>u r l</en>
    parts = re.split(r'(<en>.*?</en>)', text, flags=re.IGNORECASE)
    for idx in range(0, len(parts), 2):
        seg = parts[idx]

        def _acronym_repl(m: re.Match) -> str:
            acr = m.group(0)
            if acr in _EN_ACRONYMS:
                letters = ' '.join(acr.lower())
                return f'<en>{letters}</en>'
            return acr

        seg = re.sub(r'\b[A-Z]{2,5}\b', _acronym_repl, seg)

        # 3. Wrap contiguous English phrases (or ambiguous English homographs in English context)
        # in <en>...</en> so sea_g2p phonemizes the whole phrase smoothly as connected English speech.
        tokens = list(re.finditer(r"[A-Za-z\u00c0-\u024f\u1e00-\u1eff']+", seg))
        if len(tokens) >= 2:
            lows = [t.group(0).lower() for t in tokens]
            is_en_word = [
                (w in _UNMISTAKABLE_EN_WORDS or "'" in w or w in ('alex',))
                and all(ord(c) < 128 for c in w)
                for w in lows
            ]
            # Propagate to adjacent _AMBIGUOUS_EN_WORDS
            changed = True
            while changed:
                changed = False
                for i, w in enumerate(lows):
                    if is_en_word[i] or w not in _AMBIGUOUS_EN_WORDS:
                        continue
                    left_adj = (i > 0 and is_en_word[i - 1]
                                and seg[tokens[i - 1].end():tokens[i].start()].strip(' ,') == '')
                    right_adj = (i + 1 < len(lows) and is_en_word[i + 1]
                                 and seg[tokens[i].end():tokens[i + 1].start()].strip(' ,') == '')
                    if left_adj or right_adj:
                        is_en_word[i] = True
                        changed = True
                    # Also handle 2-word all-ambiguous common English pairs like "I am", "to go", "do it", "on me", "to be"
                    elif i + 1 < len(lows) and (w, lows[i + 1]) in {
                        ('i', 'am'), ('to', 'go'), ('do', 'it'), ('to', 'be'), ('to', 'do'),
                        ('on', 'me'), ('in', 'it'), ('let', 'me'), ('for', 'me'), ('with', 'me'),
                        ('can', 'i'), ('do', 'you'), ('can', 'you'), ('are', 'you'),
                    } and seg[tokens[i].end():tokens[i + 1].start()] == ' ':
                        is_en_word[i] = True
                        is_en_word[i + 1] = True
                        changed = True

            # Group contiguous English tokens separated only by spaces (no punctuation) into one <en>...</en> span
            rebuilt: list[str] = []
            last_pos = 0
            i = 0
            while i < len(tokens):
                tok_m = tokens[i]
                rebuilt.append(seg[last_pos:tok_m.start()])
                if is_en_word[i]:
                    j = i
                    while (j + 1 < len(tokens) and is_en_word[j + 1]
                           and seg[tokens[j].end():tokens[j + 1].start()] == ' '):
                        j += 1
                    span_text = seg[tok_m.start():tokens[j].end()]
                    # Wrap if multi-word English phrase OR if single word is an ambiguous English homograph
                    if j > i or tok_m.group(0).lower() in _AMBIGUOUS_EN_WORDS:
                        rebuilt.append(f'<en>{span_text.lower()}</en>')
                    else:
                        rebuilt.append(span_text)
                    last_pos = tokens[j].end()
                    i = j + 1
                else:
                    rebuilt.append(tok_m.group(0))
                    last_pos = tok_m.end()
                    i += 1
            rebuilt.append(seg[last_pos:])
            seg = ''.join(rebuilt)

        parts[idx] = seg

    # Merge adjacent <en>a</en> <en>b</en> -> <en>a b</en>
    merged = ''.join(parts)
    merged = re.sub(r'</en>\s+<en>', ' ', merged, flags=re.IGNORECASE)
    return merged


def shape_conversational_prosody(text: str) -> str:
    """Enhance Vietnamese conversational cadence, interjection pauses, and question/exclamation intonation for VieNeu."""
    if not text or not text.strip():
        return text
    s = text.strip()
    # 1. Map spoken laughter/sigh words to VieNeu v3 Turbo native emotion tokens ([cười], [thở dài])
    s = re.sub(r'(?i)\b(?:ha\s*ha(?:\s*ha)*|he\s*he(?:\s*he)*|hi\s*hi(?:\s*hi)*|hì\s+hì|khà\s+khà)\b[!.,]*', '[cười],', s)
    s = re.sub(r'(?i)\b(?:haizz+|haiz+)\b[!.,]*', '[thở dài],', s)
    # 2. Convert mid-sentence ellipsis to a natural breath pause comma
    s = re.sub(r'(?:\.\.\.|…)+\s+(?=[a-zà-ỹ])', ', ', s)
    # 3. Add natural micro-pause comma after leading Vietnamese interjections when missing
    s = re.sub(
        r'(?i)(^|[.!?]\s+)(ủa|à mà|à|ờ ha|ờ|ừ ha|ừm|ừ|nè|ê|ầy|ôi trời|trời ơi|thiệt ra|thật ra|nói chung là|tóm lại là)\s+(?![,.:;!?])',
        r'\1\2, ',
        s,
    )
    # 4. Restore rising question mark (?) on natural Vietnamese questions that ended with a flat period
    s = re.sub(
        r'(?i)(\b(?:sao|gì|nào|đâu|ai|chưa|hả|hở|nhỉ|không|ko|vậy|thế)\s*(?:vậy|thế|hả|nhỉ|không|đó|nữa)?)\.(?=\s|$)',
        r'\1?',
        s,
    )
    return re.sub(r'\s+', ' ', s).strip()


_VIENEU_PATCHED = False
_EN_TAG_SPLIT_RE = re.compile(r'(<en>.*?</en>)', flags=re.IGNORECASE | re.DOTALL)


def _restore_expressive_tail(original: str, processed: str) -> str:
    """Prevent sea_g2p punc_norm from flattening '?' or '!' into '.' on short (<5 word) sentences."""
    if not original or not processed:
        return processed
    orig_s = original.rstrip()
    proc_s = processed.rstrip()
    if not orig_s or not proc_s:
        return processed
    if orig_s[-1] in '?!,' and proc_s[-1] == '.':
        return proc_s[:-1] + orig_s[-1]
    return processed


def install_vieneu_normalizer_patch() -> None:
    """Prevent sea_g2p Normalizer from corrupting >10 <en> tags, double-normalizing chunks, or flattening ?/! to ."""
    global _VIENEU_PATCHED
    if _VIENEU_PATCHED:
        return
    try:
        from vieneu_utils import phonemize_text as pt
    except ImportError:
        return

    orig_punc_norm = pt.punc_norm

    def _expressive_punc_norm(text: str) -> str:
        res = orig_punc_norm(text)
        return _restore_expressive_tail(text, res)

    pt.punc_norm = _expressive_punc_norm
    orig_norm = pt.PuncNormalizer.normalize

    def _safe_normalize(self, text, punc_norm: bool = True):
        if isinstance(text, str) and '<en>' in text.lower():
            parts = _EN_TAG_SPLIT_RE.split(text)
            out: list[str] = []
            for idx, part in enumerate(parts):
                if idx % 2 == 1:
                    out.append(part.lower())
                elif part.strip():
                    lead_comma = part.lstrip().startswith(',')
                    trail_punc = ''
                    stripped = part.rstrip()
                    if stripped and stripped[-1] in ',.!?;:':
                        trail_punc = stripped[-1]
                    normed = orig_norm(self, part, punc_norm=False)
                    if normed:
                        if lead_comma and not normed.startswith(','):
                            normed = ', ' + normed
                        if trail_punc and not normed.endswith(trail_punc):
                            normed = normed.rstrip(',.!?;:') + trail_punc
                        out.append(normed)
                    elif trail_punc:
                        if out:
                            out[-1] = out[-1] + trail_punc
            res = re.sub(r'\s+', ' ', ' '.join(out)).strip()
            res = re.sub(r'\s+([,.!?;:])', r'\1', res)
            return _expressive_punc_norm(res) if punc_norm and res else res
        res = orig_norm(self, text, punc_norm=punc_norm)
        return _restore_expressive_tail(text, res) if isinstance(text, str) and isinstance(res, str) else res

    def _safe_normalize_batch(self, texts, punc_norm: bool = True):
        return [_safe_normalize(self, t, punc_norm=punc_norm) for t in texts]

    pt.PuncNormalizer.normalize = _safe_normalize
    pt.PuncNormalizer.normalize_batch = _safe_normalize_batch
    try:
        pt._phonemize_cached.cache_clear()
    except Exception:
        pass

    @functools.lru_cache(maxsize=1024)
    def _safe_phonemize_cached(text: str, punc_norm: bool = True) -> str:
        if '<en>' in text.lower():
            normed = pt._get_normalizer().normalize(text, punc_norm=punc_norm)
            res = pt._get_g2p().convert(normed, punc_norm=False)
            return _restore_expressive_tail(text, _expressive_punc_norm(res) if punc_norm else res)
        normed = pt._get_normalizer().normalize(text, punc_norm=False)
        res = pt._get_g2p().convert(normed, punc_norm=False)
        if punc_norm:
            res = _expressive_punc_norm(res)
        return _restore_expressive_tail(text, res)

    pt._phonemize_cached = _safe_phonemize_cached
    _VIENEU_PATCHED = True
