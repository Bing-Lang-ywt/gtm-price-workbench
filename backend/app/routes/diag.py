"""诊断端点（公开，无需登录）。

用于排查 Cloudflare / 公司网络 403 拦截：从公司电脑浏览器直接打开
/api/v1/diag/ip 即可看到本次请求的出口 IP 与 Cloudflare 注入的请求头，
据此判断是否被 WAF / Bot Fight Mode / 速率限制按出口 IP 拦截。
"""
import time

from fastapi import APIRouter, Request

router = APIRouter(prefix="/diag", tags=["diag"])


@router.get("/ip")
def diag_ip(request: Request):
    headers = dict(request.headers)
    # Cloudflare 注入的客户端真实出口 IP（经隧道/代理后仍为真实公网 IP）
    cf_ip = headers.get("cf-connecting-ip")
    xff = headers.get("x-forwarded-for")
    cf_ray = headers.get("cf-ray")
    # Bot Management / WAF 决策头（仅 Business+ 才有，Free 计划通常缺失 → 说明是 Free 计划）
    cf_bot_management = headers.get("cf-bot-management.verified-bot")
    cf_client_request = headers.get("cf-client-request-id")

    return {
        "cf_connecting_ip": cf_ip,
        "x_forwarded_for": xff,
        "cf_ray": cf_ray,
        "cf_bot_management_verified_bot": cf_bot_management,
        "cf_client_request_id": cf_client_request,
        "user_agent": headers.get("user-agent"),
        "server_time": int(time.time()),
        "note": (
            "若 cf_connecting_ip 不在 Cloudflare Skip 规则白名单内，"
            "则公司电脑的请求会经过 WAF / Bot Fight Mode 评估，可能被 403。"
            "请将此 IP 加入 Skip 规则，或关闭 Bot Fight Mode，或改用 Cloudflare Access。"
        ),
    }
