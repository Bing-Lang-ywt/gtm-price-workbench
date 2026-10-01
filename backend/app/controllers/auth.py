from app.services import auth as svc


def login_controller(email, password):
    return svc.login(email, password)


def me_controller(principal):
    return principal
