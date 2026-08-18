"""
Вход: приложения клиентов и администраторы панели.

У обоих один приём — токен хранится хэшем, а не открытым текстом: утечка
базы не должна отдавать живые доступы.
"""

from __future__ import annotations

import datetime as dt
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..models import Admin, AdminSession, Session, User, sanitize_device_id, utcnow
from ..security import hash_password, needs_rehash, new_token, token_hash, verify_password
from . import ratelimit
from .errors import PanelError

log = logging.getLogger("panel.auth")

# Один и тот же текст на «нет такого логина» и «пароль не тот». Разные
# формулировки превращают форму входа в справочник существующих логинов.
BAD_CREDENTIALS = "неверный логин или пароль"

# Хэш заведомо недостижимого пароля, посчитанный один раз при импорте. Нужен
# как заглушка для несуществующего логина: если считать её на месте, ветка
# «логина нет» делает два argon2 подряд вместо одного, и по времени ответа
# видно, какие логины заведены, — ровно то, чего мы избегаем.
_DUMMY_HASH = hash_password(secrets.token_hex(32))


class LoginThrottled(PanelError):
    """Слишком много попыток. `retry_after` — через сколько секунд можно."""

    def __init__(self, retry_after: int) -> None:
        minutes = max(1, round(retry_after / 60))
        super().__init__(
            f"слишком много попыток входа, попробуйте через {minutes} мин", "throttled"
        )
        self.retry_after = retry_after


# --- вход из приложения ------------------------------------------------------


# Ключ по имени учётки — это ещё и рычаг отказа в обслуживании: запереть
# чужой вход может кто угодно, кто знает логин. Поэтому лимит и окно у него
# заметно мягче, чем у пары (адрес, логин).
BY_NAME_FACTOR = 4
# Счётчик неудач с одного адреса без разбора логинов. Лимит большой: за ним
# может стоять оператор связи с общим NAT, и запирать его целиком из-за
# одного подбиральщика нельзя. Своё дело он всё равно делает — перебор
# логинов по паре (адрес, логин) не ограничен вообще, там каждый новый логин
# выглядит первой попыткой.
BY_IP_FACTOR = 10


def _norm_login(login: str) -> str:
    return login.strip().lower()[:64]


def _login_key(login: str, ip: str | None) -> str:
    return f"login:{ip or 'unknown'}:{_norm_login(login)}"


def _login_name_key(login: str) -> str:
    """
    Ключ без адреса.

    Пара (адрес, логин) не мешает подбирать пароль с пула адресов: каждый
    новый адрес — чистый счётчик. Бакет заводится для любой строки, поэтому
    429 отсюда не подсказывает, заведён такой логин или нет.
    """
    return f"login:*:{_norm_login(login)}"


def _login_ip_key(ip: str | None) -> str:
    return f"login-ip:{ip or 'unknown'}"


def reset_login_throttle(db: OrmSession, login: str, ip: str | None) -> None:
    """
    Снимает замок входа с логина — по паре (адрес, логин) и по имени.

    Зовётся после регистрации: свой только что созданный логин не должен
    оставаться запертым прежними попытками войти в ещё не существующий
    аккаунт. Счётчик по адресу (`_login_ip_key`) не трогаем — он считает
    чужой перебор с того же адреса, и своя регистрация его обнулять не
    вправе.
    """
    ratelimit.clear(db, _login_key(login, ip))
    ratelimit.clear(db, _login_name_key(login))


def authenticate(
    db: OrmSession,
    login: str,
    password: str,
    platform: str | None = None,
    app_version: str | None = None,
    ip: str | None = None,
    device_id: str | None = None,
    device_name: str | None = None,
) -> tuple[User, str]:
    """Проверяет пару логин/пароль и открывает сессию, вернув токен."""
    config = settings()
    key = _login_key(login, ip)
    name_key = _login_name_key(login)
    ip_key = _login_ip_key(ip)

    verdict = ratelimit.hit(
        db,
        key,
        limit=config.login_max_attempts,
        window_minutes=config.login_window_minutes,
        lock_minutes=config.login_lock_minutes,
    )
    if verdict.allowed:
        verdict = ratelimit.hit(
            db,
            name_key,
            limit=config.login_max_attempts * BY_NAME_FACTOR,
            window_minutes=config.login_window_minutes * BY_NAME_FACTOR,
            lock_minutes=config.login_lock_minutes,
        )
    if verdict.allowed:
        # Счётчик по адресу увеличивается только на неудачах, поэтому здесь
        # он проверяется, а не увеличивается: иначе удачные входы съедали бы
        # его сами, и общий NAT упирался бы в лимит без единого подбора.
        verdict = ratelimit.check(db, ip_key)
    if not verdict.allowed:
        log.warning("вход заперт: %s", key)
        raise LoginThrottled(verdict.retry_after)

    user = db.scalar(select(User).where(User.login == login.strip()))
    # Для несуществующего логина проверяем пароль против заглушки: одна и та
    # же argon2-операция в обеих ветках, и по времени ответа не видно, какие
    # логины заведены.
    stored = user.password_hash if user else _DUMMY_HASH
    ok = verify_password(password, stored)
    if not user or not ok:
        if user is not None:
            user.failed_logins += 1
        ratelimit.hit(
            db,
            ip_key,
            limit=config.login_max_attempts * BY_IP_FACTOR,
            window_minutes=config.login_window_minutes,
            lock_minutes=config.login_lock_minutes,
        )
        # Коммит вне ветки: get_db не коммитит сам, а одинаковый набор
        # действий в обеих ветках не даёт мерить их по времени ответа.
        db.commit()
        raise PanelError(BAD_CREDENTIALS, "bad_credentials")

    if user.is_blocked:
        raise PanelError("доступ заблокирован", "blocked")
    if not user.is_active:
        raise PanelError("доступ отключён", "disabled")

    ratelimit.clear(db, key)
    ratelimit.clear(db, name_key)
    # ip_key намеренно не сбрасываем: он считает неудачи, и своя удачная
    # попытка не должна обнулять счёт чужому перебору с того же адреса.
    #
    # Замок на самой учётке (`User.locked_until`, `is_locked_out`) не
    # используется: он отвечал бы 429 на запертый логин и 401 на
    # несуществующий, то есть работал бы справочником заведённых логинов.
    # Ту же работу делает `name_key` — и делает её для любой строки.
    user.failed_logins = 0
    user.last_login_at = utcnow()

    # Пароль есть открытым текстом только здесь и только сейчас — другого
    # повода перевести старый scrypt-хэш на argon2id не будет.
    if needs_rehash(stored):
        user.password_hash = hash_password(password)

    token = new_token()
    session = Session(
        user_id=user.id,
        token_hash=token_hash(token),
        platform=platform,
        app_version=app_version,
        ip=ip,
        # Идентификатор приходит от клиента, а `ios-N` — служебные слоты
        # ключей AmneziaVPN, которые заводит панель. Приложение с таким
        # идентификатором путалось бы с ними в списках ключей.
        device_id=sanitize_device_id(device_id),
        device_name=device_name,
        expires_at=utcnow() + dt.timedelta(days=config.client_token_days),
    )
    db.add(session)
    db.commit()

    _enforce_device_limit(db, user, session)
    return user, token


def _enforce_device_limit(db: OrmSession, user: User, current: Session) -> None:
    """
    Держит число устройств в пределах тарифа.

    Вход не запрещаем, а гасим самый старый сеанс. Отказать человеку,
    который только что заплатил, потому что он забыл выйти на старом
    телефоне, — верный способ получить обращение в поддержку вместо
    работающего сервиса. Тот, кого выкинули, увидит это на своём устройстве
    и войдёт заново, если оно ему нужно.

    Личный кабинет в браузере лимит не занимает и под него не попадает:
    туннеля там нет, отключать нечего. Пока браузер считался устройством,
    человек заходил в кабинет посмотреть срок подписки — и выкидывал этим
    собственный телефон из VPN.
    """
    now = utcnow()
    live = [s for s in user.live_sessions() if s.id != current.id]

    # Повторный вход с того же устройства — не второе устройство. Гасим
    # прежний сеанс этой установки, чтобы переустановка не съедала лимит.
    # Браузеру это тоже нужно, и по той же причине: иначе каждый вход в
    # кабинет оставлял бы в списке ещё одну живую строку.
    if current.device_id:
        for session in live:
            if session.device_id == current.device_id:
                session.revoked_at = now
        live = [s for s in live if s.device_id != current.device_id]

    if not current.is_device:
        db.commit()
        return

    limit = user.device_limit()
    if limit <= 0:
        db.commit()
        return

    devices = [s for s in live if s.is_device]
    excess = len(devices) + 1 - limit
    if excess > 0:
        for session in sorted(devices, key=lambda s: s.last_seen_at)[:excess]:
            # Не просто гасим токен, а отключаем по-настоящему: пир
            # выкинутого устройства обязан уйти с узла, иначе оно продолжит
            # ходить в VPN уже поднятым туннелем.
            from .devices import disconnect

            disconnect(db, session, reason="лимит тарифа")
            log.info("устройство отвязано по лимиту тарифа: пользователь %s", user.public_id)
    db.commit()


def session_for_token(db: OrmSession, token: str) -> Session | None:
    session = db.scalar(select(Session).where(Session.token_hash == token_hash(token)))
    if session is None or session.revoked_at is not None:
        return None
    if session.expires_at <= utcnow():
        return None
    return session


def touch(db: OrmSession, session: Session, ip: str | None = None) -> None:
    now = utcnow()
    session.last_seen_at = now
    if ip:
        session.ip = ip

    # Обещание из config.client_token_days («активный пользователь не
    # разлогинивается») выполняет панель: приложение хранит один токен и на
    # 401 стирает настройки — тихо перелогиниться оно не умеет, а пароль
    # человеку показывали один раз на странице успеха. Поэтому окно
    # скользящее: продлеваем, когда от срока осталось меньше половины.
    full = dt.timedelta(days=settings().client_token_days)
    if session.expires_at - now < full / 2:
        session.expires_at = now + full
    db.commit()


# --- вход в панель -----------------------------------------------------------


# Лимит по имени администратора. Щедрее клиентского намеренно: админ в
# панели один, и запертая посторонним учётка — это отказ в обслуживании
# всей панели, а не одного человека. Подбор пароля полсотни попыток в час
# всё равно не даёт.
ADMIN_BY_NAME_FACTOR = 10


def _admin_key(login: str, ip: str | None) -> str:
    return f"admin-login:{ip or 'unknown'}:{_norm_login(login)}"


def _admin_name_key(login: str) -> str:
    return f"admin-login:*:{_norm_login(login)}"


def _admin_ip_key(ip: str | None) -> str:
    return f"admin-login-ip:{ip or 'unknown'}"


def authenticate_admin(
    db: OrmSession, login: str, password: str, ip: str | None = None
) -> tuple[Admin, str, dt.datetime]:
    """
    Вход в панель. Ограничен по частоте так же, как вход клиента.

    Ключа три, и каждый закрывает то, что не закрывают остальные. Пара
    (адрес, логин) — обычный подбор. Отдельный счётчик по имени учётки —
    подбор с пула адресов: администратор в панели один, логин у него
    заведомо известен, и без этого ключа пул адресов обходил бы защиту
    целиком. Счётчик по адресу — перебор логинов с одного места.
    """
    config = settings()
    key = _admin_key(login, ip)
    name_key = _admin_name_key(login)
    ip_key = _admin_ip_key(ip)

    verdict = ratelimit.hit(
        db,
        key,
        limit=config.login_max_attempts,
        window_minutes=config.login_window_minutes,
        lock_minutes=config.login_lock_minutes,
    )
    if verdict.allowed:
        verdict = ratelimit.hit(
            db,
            name_key,
            limit=config.login_max_attempts * ADMIN_BY_NAME_FACTOR,
            window_minutes=config.login_window_minutes * BY_NAME_FACTOR,
            lock_minutes=config.login_lock_minutes,
        )
    if verdict.allowed:
        verdict = ratelimit.check(db, ip_key)
    if not verdict.allowed:
        log.warning("вход в панель заперт: %s", key)
        raise LoginThrottled(verdict.retry_after)

    admin = db.scalar(select(Admin).where(Admin.login == login.strip()))
    stored = admin.password_hash if admin else _DUMMY_HASH
    ok = verify_password(password, stored)
    if not admin or not ok:
        ratelimit.hit(
            db,
            ip_key,
            limit=config.login_max_attempts * BY_IP_FACTOR,
            window_minutes=config.login_window_minutes,
            lock_minutes=config.login_lock_minutes,
        )
        raise PanelError("неверный логин или пароль")

    # Без сброса администратор, дважды опечатавшийся в пароле, запирает сам
    # себя на login_lock_minutes.
    ratelimit.clear(db, key)
    ratelimit.clear(db, name_key)

    token = new_token()
    expires_at = utcnow() + dt.timedelta(days=settings().admin_token_days)
    db.add(AdminSession(admin_id=admin.id, token_hash=token_hash(token), expires_at=expires_at))
    db.commit()
    return admin, token, expires_at


def admin_session_for_token(db: OrmSession, token: str) -> AdminSession | None:
    session = db.scalar(select(AdminSession).where(AdminSession.token_hash == token_hash(token)))
    if session is None or session.revoked_at is not None:
        return None
    if session.expires_at <= utcnow():
        return None
    return session


def revoke_admin_session(db: OrmSession, session: AdminSession) -> None:
    session.revoked_at = utcnow()
    db.commit()
