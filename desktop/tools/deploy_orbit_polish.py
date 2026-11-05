"""One-time guarded update of the existing Alex observatory. No UI/OS actions."""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import shutil

stage=Path(__file__).resolve().parents[1]
project=Path(r'D:\HỌC TẬP\dự án trợ lý ảo')
source=project/'trợ lý ảo-local/source/alex-assistant/desktop'
live=project/'trợ lý ảo-local/outputs/Bionic-pet'
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest().upper()
expected={
    'pet/space_view.py':'E33B335FE96A005DFEB82A242526D5FE17925FCE2E9C9FCE8BC1594013185B3F',
    'ORBIT-DESKTOP.md':'4CC2D315611CFAF41F9C141E598423D0E50859EB96997CB11A55F5BACF854F6C',
}
common=list(expected)+['pet/orbit_scene.py','pet/planet_art.py']
extra=['tests/test_space_view.py','tools/preview_orbit.py','tools/deploy_orbit_polish.py']
for name,value in {
    'tests/test_space_view.py':'1512373A9E48F64E6108B564BA3DBA1BBE7C9EEAC05887974544420F43253917',
    'tools/preview_orbit.py':'C1EE1DD8308F45DAA9775406BA4AC19051AFA2F3FFB591E634A9AB211AB60361',
}.items():
    if digest(source/name)!=value: raise SystemExit('Source test/tool changed; inspect first: '+name)
for root in (source,live):
    for name,value in expected.items():
        if digest(root/name)!=value: raise SystemExit('Existing file changed; inspect before deploying: '+name)
    for name in ('pet/orbit_scene.py','pet/planet_art.py'):
        if (root/name).exists(): raise SystemExit('New module already exists; inspect before deployment: '+name)
guide=project/'Alex-Desktop/ORBIT-DESKTOP.md'
if digest(guide)!=expected['ORBIT-DESKTOP.md']: raise SystemExit('Installed guide changed; inspect first.')
tests=json.loads((stage/'orbit-tests.json').read_text(encoding='utf-8'))
if not tests['passed'] or tests['tests']<27: raise SystemExit('Required tests did not pass.')
tag=datetime.now().strftime('%Y%m%d-%H%M%S')
backup=project/'Luu-tru'/('truoc-vu-tru-polish-'+tag)
report=project/'Bao-cao'/('vu-tru-polish-'+tag)
backup.mkdir(parents=True,exist_ok=False); report.mkdir(parents=True,exist_ok=False)
changes=[]
for group,root,files in (('source',source,common+extra),('live',live,common)):
    for name in files:
        target=root/name
        target.resolve().relative_to(project.resolve())
        before=None
        if target.exists():
            before=digest(target); saved=backup/group/name
            saved.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(target,saved)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(stage/name,target)
        if digest(target)!=digest(stage/name): raise RuntimeError('Copy verification failed: '+name)
        changes.append({'file':str(target),'before':before,'after':digest(target)})
shutil.copy2(guide,backup/'ORBIT-DESKTOP.md'); shutil.copy2(stage/'ORBIT-DESKTOP.md',guide)
for name in ('orbit-tests.json','orbit-tests.txt','preview-space.png','preview-space-small.png',
             'preview-space-compact.png','preview-space-saturn.png','ORBIT-DESKTOP.md'):
    shutil.copy2(stage/name,report/name)
shutil.copy2(Path(__file__),report/Path(__file__).name)
(report/'changes.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2),encoding='utf-8')
handoff=project/'ALEX-HANDOFF-CODEX-ANTIGRAVITY.md'
shutil.copy2(handoff,backup/handoff.name)
with handoff.open('a',encoding='utf-8') as f:
    f.write(f'''

## 28/10/2026 — Vũ trụ Alex: Đài quan sát

Đã nâng cấp giao diện Vũ trụ: nền sao/tinh vân cache, quỹ đạo hai độ sáng theo chiều
sâu, vệt chuyển động, vành đai tiểu hành tinh minh họa. Hành tinh có ảnh vẽ riêng tại
máy (lục địa/mây, dải khí, vành đai Sao Thổ); đây là hình nghệ thuật, không phải bản đồ
khoa học. Mặt Trăng nhỏ minh họa khi chọn Trái Đất. Thông số quỹ đạo PLANETS giữ nguyên.

Bảng bên phải có cận cảnh, chu kỳ/khoảng cách, chọn Trước/Tiếp/danh sách. Tham quan
tự động chuyển hành tinh mỗi 9 giây; tạm dừng hoặc ẩn trang dừng bộ hẹn giờ. Có góc
nghiêng/nhìn từ trên, bật/tắt quỹ đạo/tên/vệt sáng. Layout đã kiểm tra tới 800×580.

Tách OrbitCanvas sang `pet/orbit_scene.py`, minh họa sang `pet/planet_art.py`;
`pet/space_view.py` vẫn export OrbitCanvas và giữ CameraSession, SpacePage API.
Tối đa 9 sprite 448×448, chia sẻ giữa mô hình/cận cảnh; cache nền theo size/DPI và
quỹ đạo theo pose/size. Không thêm dependency, không fetch asset hoặc gửi dữ liệu.
Camera vẫn opt-in, dừng khi ẩn/minimize, không tự bật lại. Không sửa mic/STT/LLM,
router, APK, Unlock, firewall hoặc pet bên ngoài. Không push GitHub.

27 tests đạt (Qt offscreen + process camera giả); kiểm tra tour/pause/hide, cache,
chọn hành tinh bằng chuột, kích thước nhỏ và các chức năng cũ. Render 1000×500:
mean {tests['offscreen_render_ms_mean']} ms, p95 {tests['offscreen_render_ms_p95']} ms.
Đây là bài đo vẽ, không phải FPS hoặc CPU toàn máy. Chưa bật camera/mic thật.
Báo cáo `{report.relative_to(project)}`; backup `{backup.relative_to(project)}`.
Xem deployment.json để biết trạng thái restart và xác minh cửa sổ thật.
''')
result={'report':str(report),'backup':str(backup),'deployed':True,'restart_required':True,
        'live_ui_verified':False,'tests_passed':tests['tests'],'camera_opened':False}
payload=json.dumps(result,ensure_ascii=False,indent=2)
(report/'deployment.json').write_text(payload,encoding='utf-8')
(stage/'orbit-polish-deployment.json').write_text(payload,encoding='utf-8')
print(json.dumps(result,ensure_ascii=True))
