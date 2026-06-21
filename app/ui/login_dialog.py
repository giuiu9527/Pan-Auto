"""内嵌浏览器登录百度网盘。

在软件内打开百度官方登录页，用户用任意方式（账号密码 / 扫码 / 短信）登录，
登录成功后从浏览器 Cookie 中抓取 BDUSS / STOKEN 等，回传给主程序。

这种方式不依赖任何私有接口，最稳定。
"""
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
)
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

from app.config import DATA_DIR

LOGIN_URL = "https://pan.baidu.com/"
SUCCESS_HINT = "disk/home"  # 登录成功后会跳到网盘首页


class LoginDialog(QDialog):
    # 登录成功，回传 cookies dict
    logged_in = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("登录百度网盘")
        self.resize(960, 680)
        self.cookies: dict[str, str] = {}
        self._done = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部提示条
        bar = QHBoxLayout()
        bar.setContentsMargins(14, 8, 14, 8)
        self.hint = QLabel("请在下方页面登录你的百度网盘账号，登录成功后会自动完成。")
        self.hint.setStyleSheet("color:#4b5563;")
        bar.addWidget(self.hint)
        bar.addStretch()
        reload_btn = QPushButton("刷新")
        reload_btn.setObjectName("Ghost")
        reload_btn.clicked.connect(lambda: self.view.reload())
        self.finish_btn = QPushButton("我已登录，完成")
        self.finish_btn.setObjectName("Primary")
        self.finish_btn.clicked.connect(self._try_finish)
        bar.addWidget(reload_btn)
        bar.addWidget(self.finish_btn)
        wrap = QLabel()
        root.addLayout(bar)

        # 独立 profile，持久化在用户数据目录，便于记住登录
        self.profile = QWebEngineProfile("panauto", self)
        self.profile.setPersistentStoragePath(str(DATA_DIR / "webprofile"))
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        self.cookie_store = self.profile.cookieStore()
        self.cookie_store.cookieAdded.connect(self._on_cookie)

        self.page = QWebEnginePage(self.profile, self)
        self.view = QWebEngineView()
        self.view.setPage(self.page)
        self.view.urlChanged.connect(self._on_url)
        self.view.load(QUrl(LOGIN_URL))
        root.addWidget(self.view, 1)

    # 收集所有 Cookie
    def _on_cookie(self, cookie: QNetworkCookie):
        name = bytes(cookie.name()).decode("utf-8", "ignore")
        value = bytes(cookie.value()).decode("utf-8", "ignore")
        if name:
            self.cookies[name] = value
        # 关键 Cookie 齐了就提示可以完成
        if "BDUSS" in self.cookies:
            self.hint.setText("检测到登录信息，正在确认…")

    def _on_url(self, url: QUrl):
        if SUCCESS_HINT in url.toString() and "BDUSS" in self.cookies:
            # 跳到网盘首页且已有 BDUSS → 登录成功
            self._try_finish()

    def _try_finish(self):
        if self._done:
            return
        if "BDUSS" not in self.cookies:
            self.hint.setText("尚未检测到登录，请先在页面内完成登录。")
            return
        self._done = True
        self.logged_in.emit(dict(self.cookies))
        self.accept()
