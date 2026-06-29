#!/usr/bin/env python3
import argparse
import importlib.util
import sys
import types
from pathlib import Path


def _install_module(name):
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


def install_moviepilot_stubs():
    pytz = _install_module("pytz")
    pytz.timezone = lambda name: None

    app = _install_module("app")
    schemas = _install_module("app.schemas")
    app.schemas = schemas
    schemas.NotificationType = type("NotificationType", (), {})
    schemas.TorrentInfo = type("TorrentInfo", (), {})
    schemas.MediaType = type("MediaType", (), {})
    schemas.ServiceInfo = type("ServiceInfo", (), {})

    helper = _install_module("app.helper")
    helper_sites = _install_module("app.helper.sites")
    helper_sites.SitesHelper = type("SitesHelper", (), {"get_indexers": lambda self: []})
    helper_downloader = _install_module("app.helper.downloader")
    helper_downloader.DownloaderHelper = type("DownloaderHelper", (), {"get_configs": lambda self: {}})
    app.helper = helper

    core = _install_module("app.core")
    core_config = _install_module("app.core.config")
    core_config.settings = types.SimpleNamespace(TORRENT_TAG="MOVIEPILOT", TZ="Asia/Shanghai", PROXY=None)
    core_context = _install_module("app.core.context")
    core_context.MediaInfo = type("MediaInfo", (), {})
    core_metainfo = _install_module("app.core.metainfo")
    core_metainfo.MetaInfo = type("MetaInfo", (), {})
    app.core = core

    db = _install_module("app.db")
    db_site_oper = _install_module("app.db.site_oper")
    db_site_oper.SiteOper = type("SiteOper", (), {})
    db_subscribe_oper = _install_module("app.db.subscribe_oper")
    db_subscribe_oper.SubscribeOper = type("SubscribeOper", (), {})
    app.db = db

    chain = _install_module("app.chain")
    chain_torrents = _install_module("app.chain.torrents")
    chain_torrents.TorrentsChain = type("TorrentsChain", (), {})
    app.chain = chain

    log_module = _install_module("app.log")
    log_module.logger = type("Logger", (), {
        "debug": staticmethod(lambda *args, **kwargs: None),
        "info": staticmethod(lambda *args, **kwargs: None),
        "warning": staticmethod(lambda *args, **kwargs: None),
        "error": staticmethod(lambda *args, **kwargs: None),
    })()
    app.log = log_module

    modules = _install_module("app.modules")
    qbittorrent = _install_module("app.modules.qbittorrent")
    qbittorrent.Qbittorrent = type("Qbittorrent", (), {})
    transmission = _install_module("app.modules.transmission")
    transmission.Transmission = type("Transmission", (), {})
    app.modules = modules

    plugins = _install_module("app.plugins")
    plugins._PluginBase = type("PluginBase", (), {"update_config": lambda self, *args, **kwargs: None})
    app.plugins = plugins

    schemas_types = _install_module("app.schemas.types")
    schemas_types.EventType = type("EventType", (), {"PluginTriggered": "PluginTriggered"})

    utils = _install_module("app.utils")
    utils_http = _install_module("app.utils.http")
    utils_http.RequestUtils = type("RequestUtils", (), {})
    utils_string = _install_module("app.utils.string")
    utils_string.StringUtils = type("StringUtils", (), {
        "str_filesize": staticmethod(lambda value: str(value)),
        "str_to_timestamp": staticmethod(lambda value: None),
        "generate_random_str": staticmethod(lambda length: "RANDOMTAG"),
        "get_url_domain": staticmethod(lambda value: value),
    })
    app.utils = utils

    apscheduler = _install_module("apscheduler")
    schedulers = _install_module("apscheduler.schedulers")
    background = _install_module("apscheduler.schedulers.background")
    background.BackgroundScheduler = type("BackgroundScheduler", (), {})
    triggers = _install_module("apscheduler.triggers")
    cron = _install_module("apscheduler.triggers.cron")
    cron.CronTrigger = type("CronTrigger", (), {"from_crontab": staticmethod(lambda *args, **kwargs: None)})
    apscheduler.schedulers = schedulers
    apscheduler.triggers = triggers


def load_plugin_module():
    install_moviepilot_stubs()
    plugin_path = Path(__file__).resolve().parents[1] / "plugins.v2" / "brushflowlowfreq" / "__init__.py"
    spec = importlib.util.spec_from_file_location("brushflowlowfreq_preview", plugin_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_component(node):
    if isinstance(node, list):
        return "".join(build_component(child) for child in node)
    if not isinstance(node, dict):
        return ""

    component = node.get("component")
    props = node.get("props") or {}
    content = node.get("content") or []
    text = node.get("text")
    html = node.get("html")

    if component in {"VForm", "VCard", "VCardText", "VWindow", "VWindowItem"}:
        cls = component.lower()
        extra = f' data-value="{props.get("value", "")}"' if props.get("value") else ""
        return f'<div class="{cls}"{extra}>' + "".join(build_component(child) for child in content) + "</div>"

    if component == "VTabs":
        return '<div class="tabs">' + "".join(build_component(child) for child in content) + "</div>"

    if component == "VTab":
        active = " active" if props.get("value") == "upload_protection_tab" else ""
        return f'<div class="tab{active}">{text or props.get("label") or props.get("value") or ""}</div>'

    if component == "VRow":
        style = props.get("style") or {}
        style_text = "; ".join(f"{k}: {v}" for k, v in style.items())
        return f'<div class="row" style="{style_text}">' + "".join(build_component(child) for child in content) + "</div>"

    if component == "VCol":
        col = props.get("md") or props.get("cols") or 12
        return f'<div class="col span-{col}">' + "".join(build_component(child) for child in content) + "</div>"

    if component in {"VSwitch", "VSelect", "VTextField", "VCronField", "VAceEditor"}:
        label = props.get("label", component)
        hint = props.get("hint") or props.get("placeholder") or ""
        model = props.get("model") or props.get("modelvalue") or ""
        items = props.get("items") or []
        if component == "VSelect":
            option_html = "".join(
                f'<option>{item.get("title", "")}</option>' for item in items
            )
            return (
                '<label class="field">'
                f'<span class="field-label">{label}</span>'
                f'<div class="field-box"><select>{option_html}</select></div>'
                f'<div class="field-meta">{model}{(" | " + hint) if hint else ""}</div>'
                "</label>"
            )
        tag = "textarea" if component == "VAceEditor" else "input"
        input_type = "text" if component != "VSwitch" else "checkbox"
        value_attr = "" if component == "VSwitch" else f' placeholder="{hint}"'
        return (
            '<label class="field">'
            f'<span class="field-label">{label}</span>'
            + (f'<div class="field-box"><{tag} type="{input_type}"{value_attr}></{tag}></div>'
               if tag == "textarea"
               else f'<div class="field-box"><input type="{input_type}"{value_attr}></div>')
            + f'<div class="field-meta">{model}{(" | " + hint) if hint else ""}</div></label>'
        )

    if component in {"div", "span", "u", "a"}:
        tag = component
        attrs = []
        if component == "a":
            attrs.append(f'href="{props.get("href", "#")}"')
            if props.get("target"):
                attrs.append(f'target="{props.get("target")}"')
        if component == "div" and props.get("class"):
            attrs.append(f'class="{props.get("class")}"')
        inner = text or html or "".join(build_component(child) for child in content)
        return f'<{tag} {" ".join(attrs)}>{inner}</{tag}>'

    if text is not None:
        return f"<div class='text'>{text}</div>"
    if html is not None:
        return f"<div class='html'>{html}</div>"
    return "".join(build_component(child) for child in content)


def build_preview_html(form):
    body = build_component(form)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BrushFlowLowFreq 预览</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f7fb; color: #1f2937; }}
    .wrap {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}
    .form {{ display: grid; gap: 16px; }}
    .vform, .vcard, .vcardtext, .vwindow, .vwindowitem {{ display: grid; gap: 12px; }}
    .tabs {{ display: flex; gap: 8px; flex-wrap: wrap; padding: 12px; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; }}
    .tab {{ padding: 8px 12px; border-radius: 6px; background: #f3f4f6; font-size: 14px; }}
    .tab.active {{ background: #111827; color: #fff; }}
    .row {{ display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 12px; align-items: start; }}
    .col {{ min-width: 0; }}
    .field {{ display: grid; gap: 6px; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; box-sizing: border-box; min-height: 84px; }}
    .field-label {{ font-size: 13px; font-weight: 600; line-height: 1.3; }}
    .field-box {{ min-height: 34px; display: flex; align-items: center; }}
    .field-box input, .field-box select, .field-box textarea {{ width: 100%; box-sizing: border-box; border: 1px solid #d1d5db; border-radius: 6px; padding: 8px 10px; background: #fafafa; font-size: 13px; }}
    .field-box textarea {{ min-height: 80px; resize: vertical; }}
    .field-meta {{ font-size: 12px; color: #6b7280; line-height: 1.3; }}
    .span-12 {{ grid-column: span 12; }}
    .span-6 {{ grid-column: span 6; }}
    .span-4 {{ grid-column: span 4; }}
    .span-3 {{ grid-column: span 3; }}
    .span-2 {{ grid-column: span 2; }}
    .span-1 {{ grid-column: span 1; }}
    .alert {{ padding: 12px 14px; border-radius: 8px; background: #fff; border: 1px solid #e5e7eb; }}
    .text-subtitle-2 {{ font-size: 14px; }}
    .font-weight-bold {{ font-weight: 700; }}
    .mt-2 {{ margin-top: 8px; }}
    .mb-1 {{ margin-bottom: 4px; }}
    @media (max-width: 960px) {{
      .row {{ grid-template-columns: repeat(1, minmax(0, 1fr)); }}
      .span-12, .span-6, .span-4, .span-3, .span-2, .span-1 {{ grid-column: span 1; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="form">{body}</div>
  </div>
</body>
</html>"""
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("/tmp/brushflowlowfreq-preview.html"))
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    module = load_plugin_module()
    plugin = module.BrushFlowLowFreq()
    plugin.sites_helper = types.SimpleNamespace(get_indexers=lambda: [])
    plugin.downloader_helper = types.SimpleNamespace(get_configs=lambda: {})
    form, _defaults = plugin.get_form()
    html = build_preview_html(form)
    args.output.write_text(html, encoding="utf-8")
    print(args.output)

    if args.serve:
        from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
        from urllib.parse import urlparse

        class PreviewHandler(BaseHTTPRequestHandler):
            html = html

            def do_GET(self):
                path = urlparse(self.path).path
                if path not in ("/", "/index.html"):
                    self.send_error(404)
                    return
                payload = self.html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, fmt, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", args.port), PreviewHandler)
        print(f"http://127.0.0.1:{args.port}/")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
