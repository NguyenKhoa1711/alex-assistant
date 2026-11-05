"""One-time checked deployment of the hologram page; backs up every replaced file."""
from pathlib import Path
from datetime import datetime
import hashlib,json,shutil

stage=Path(__file__).resolve().parents[1]
project=Path(r'D:\HỌC TẬP\dự án trợ lý ảo')
repo=project/'trợ lý ảo-local/source/alex-assistant/desktop'
live=project/'trợ lý ảo-local/outputs/Bionic-pet'
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest().upper()
expected={
 'pet/app_window.py':'5345F6E8DC23CDE5E68916E6530D5D310288F6CC747C9835A0340BC0123F9C0C',
 'pet/command_center.py':'5E0C018DCADA7A2736882ECBFBABB726A61D5BD22D67CFF54E3ACA193E734EAC',
 'tests/test_space_view.py':'3CDF451AAFEF1B237005B3CE874F0CBC231D73258ADC7A5C0472E72E27FECF8D',
 'tools/preview_orbit.py':'C1E9C025C5F3892125B384C250EF87E5A1AC3462C241BEAA73698C6045EA29A4',
}
common=['pet/app_window.py','pet/command_center.py','pet/hologram_face.py','COMMAND-CENTER-HOLOGRAM.md']
extra=['tests/test_space_view.py','tests/test_hologram_center.py','tools/preview_orbit.py',
       'tools/verify_hologram.py','tools/deploy_hologram.py']
for group,root,files in [('source',repo,common+extra),('live',live,common)]:
    for name in files:
        path=root/name
        path.resolve().relative_to(project.resolve())
        if name in expected:
            if digest(path)!=expected[name]: raise SystemExit(f'File changed since inspection: {path}')
        elif path.exists(): raise SystemExit(f'New file already exists: {path}')
tests=json.loads((stage/'hologram-tests.json').read_text())
if not tests['passed']: raise SystemExit('Tests did not pass')
tag=datetime.now().strftime('%Y%m%d-%H%M%S')
backup=project/'Luu-tru'/('truoc-hologram-'+tag)
report=project/'Bao-cao'/('alex-hologram-'+tag)
backup.mkdir(parents=True,exist_ok=False); report.mkdir(parents=True,exist_ok=False)
changes=[]
for group,root,files in [('source',repo,common+extra),('live',live,common)]:
    for name in files:
        path=root/name; before=None
        if path.exists():
            before=digest(path); saved=backup/group/name; saved.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,saved)
        path.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(stage/name,path)
        if digest(path)!=digest(stage/name): raise RuntimeError('Hash mismatch')
        changes.append({'path':str(path),'before':before,'after':digest(path)})
guide=project/'Alex-Desktop/COMMAND-CENTER-HOLOGRAM.md'
if guide.exists(): shutil.copy2(guide,backup/'COMMAND-CENTER-HOLOGRAM.md')
shutil.copy2(stage/'COMMAND-CENTER-HOLOGRAM.md',guide)
for name in ('hologram-tests.json','hologram-tests.txt','hologram-paused.png','hologram-listening.png',
             'hologram-compact.png','COMMAND-CENTER-HOLOGRAM.md'):
    shutil.copy2(stage/name,report/name)
(report/'changes.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2),encoding='utf-8')
handoff=project/'ALEX-HANDOFF-CODEX-ANTIGRAVITY.md'
shutil.copy2(handoff,backup/handoff.name)
with handoff.open('a',encoding='utf-8') as f:
    f.write(f'''\n## Trạm chỉ huy hologram — {tag}

Theo clip Cwt-Jz6-sEw (FatihMakes), thay reactor robot trong Trạm chỉ huy bằng mặt đa giác xanh,
mắt vàng, nền HUD tối đồng bộ thanh bên. Lưới 3D tự dựng bằng QPainter và cache QPixmap;
không tải model/kịch bản từ clip. Hướng đầu theo chuột trong vùng mặt. Biểu cảm dùng state
thật của Controller, miệng là animation khi speaking (không phải lip sync theo âm vị).
CPU/RAM đọc thật, 30 mẫu trong RAM. Nút giảm chuyển động; timer dừng khi rời trang/minimize.
Không đổi pet desktop, router, mic, camera, quyền, Android, Unlock hoặc Bionic.

{tests['tests']} tests offscreen đạt. Render cache 520×520: trung bình {tests['hologram_render_mean_ms']} ms,
p95 {tests['hologram_render_p95_ms']} ms trong bài đo, không phải số đo CPU tổng thể hay cam kết FPS.
Chưa thử mic thật. Cần xem deployment.json trong báo cáo để biết restart/live UI đã xác minh chưa.
Báo cáo `{report.relative_to(project)}`; backup `{backup.relative_to(project)}`.
Không chạy lại script deploy một lần. Chưa push GitHub.
''')
result={'report':str(report),'backup':str(backup),'deployed':True,'restart_required':True,
        'live_ui_verified':False,'tests_passed':tests['tests'],'camera_opened':False}
(report/'deployment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
(stage/'hologram-deployment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=True))
