import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QPixmap
from pet.config import load_config, ROOT
from pet.controller import Controller
from pet.window import PetWindow

app = QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
cfg = load_config()
engine = Controller(cfg)
window = PetWindow(cfg, engine)
window.show()
window.phase = 30
app.processEvents()
window.set_state('idle', 'Gọi “A lếch” để hỏi')
window.grab().save(str(ROOT / 'preview.png'))
states = (
    ('idle', 'Mình đang ở đây'),
    ('listening', 'Mình đang nghe bạn'),
    ('thinking', 'Đang suy nghĩ…'),
    ('speaking', 'Mình đang trả lời'),
)
shapes = ('mascot', 'robot', 'cat', 'blob')
sheet = QPixmap(window.width() * len(shapes), window.height() * len(states))
sheet.fill(QColor('#eaf0f4'))
painter = QPainter(sheet)
for column, shape in enumerate(shapes):
    window.shape = shape
    for row, (mode, caption) in enumerate(states):
        window.set_state(mode, caption)
        app.processEvents()
        painter.drawPixmap(column * window.width(), row * window.height(), window.grab())
painter.end()
sheet.save(str(ROOT / 'preview-states.png'))
print('Preview and state sheet saved')
