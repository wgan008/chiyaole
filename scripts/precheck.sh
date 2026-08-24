#!/usr/bin/env bash
# ============================================================================
#  吃药了 · 设备兼容性预检  (ChiYaoLe device pre-flight check)
#
#  用法：手机开启「开发者选项 → USB 调试」，用数据线连电脑，然后
#      ./precheck.sh              检查当前连接的设备
#      ./precheck.sh -s <serial>  指定设备
#
#  退出码：0=可用  1=有降级风险  2=不兼容，别装
# ============================================================================
set -uo pipefail

ADB="adb"
[[ "${1:-}" == "-s" && -n "${2:-}" ]] && ADB="adb -s $2"

R=$'\e[31m'; G=$'\e[32m'; Y=$'\e[33m'; B=$'\e[1m'; D=$'\e[2m'; N=$'\e[0m'
FATAL=0; WARN=0

say()  { printf '%s\n' "$*"; }
ok()   { printf "  ${G}✓${N} %s\n" "$*"; }
warn() { printf "  ${Y}!${N} %s\n" "$*"; WARN=$((WARN+1)); }
bad()  { printf "  ${R}✗${N} %s\n" "$*"; FATAL=$((FATAL+1)); }
hdr()  { printf "\n${B}%s${N}\n" "$*"; }

prop() { $ADB shell getprop "$1" 2>/dev/null | tr -d '\r'; }

# ---------------------------------------------------------------- 连接检查
if ! $ADB get-state >/dev/null 2>&1; then
  printf "${R}没有检测到设备。${N}\n"
  say "请确认：① 数据线连好  ② 开发者选项→USB调试 已开  ③ 手机上点了「允许调试」"
  exit 2
fi

printf "${B}吃药了 · 设备兼容性预检${N}\n"
printf "${D}%s${N}\n" "$(date '+%Y-%m-%d %H:%M:%S')"

# ---------------------------------------------------------------- 基本信息
hdr "设备"
BRAND=$(prop ro.product.brand)
MODEL=$(prop ro.product.model)
MANUF=$(prop ro.product.manufacturer)
SDK=$(prop ro.build.version.sdk)
REL=$(prop ro.build.version.release)
# 鸿蒙/EMUI 版本（华为设备才有）
EMUI=$(prop ro.build.version.emui)
HMOS=$(prop hw_sc.build.platform.version)
[[ -z "$EMUI" ]] && EMUI=$(prop ro.build.version.harmonyos)

printf "  品牌型号 : %s %s (%s)\n" "$BRAND" "$MODEL" "$MANUF"
printf "  Android  : %s  ${B}API %s${N}\n" "$REL" "$SDK"
[[ -n "$EMUI" ]] && printf "  鸿蒙/EMUI: %s\n" "$EMUI"
[[ -n "$HMOS" ]] && printf "  平台版本 : %s\n" "$HMOS"

# ---------------------------------------------------------------- 致命项
hdr "① 能不能装（致命项）"

# HarmonyOS NEXT：无 AOSP 兼容层，APK 完全装不了。
# 判据：能连上 adb 且能读 ro.build.version.sdk，基本说明有 AOSP 层。
# NEXT 设备通常读不到该属性或 adb 行为完全不同。
if [[ -z "$SDK" || ! "$SDK" =~ ^[0-9]+$ ]]; then
  bad "读不到 Android API level —— 可能是 HarmonyOS NEXT（纯血鸿蒙），APK 装不了"
  say "     → 走降级方案：大字用药表设锁屏 + 子女端网页"
else
  if (( SDK < 26 )); then
    bad "API $SDK 低于 minSdk 26（Android 8.0），装不了"
  else
    ok "API $SDK ≥ 26，可安装"
  fi
fi

# 未知来源安装
UNK=$($ADB shell settings get secure install_non_market_apps 2>/dev/null | tr -d '\r')
if [[ "$UNK" == "0" ]]; then
  warn "「安装未知来源应用」未开启（旧机型全局开关）"
else
  ok "未知来源安装：未被全局禁用"
fi

# 华为纯净模式（属性名各版本不一，读不到就提示手查）
if [[ "$MANUF" =~ [Hh][Uu][Aa][Ww][Ee][Ii] || "$BRAND" =~ [Hh][Oo][Nn][Oo][Rr] ]]; then
  PURE=$($ADB shell settings get global pure_mode_state 2>/dev/null | tr -d '\r')
  if [[ "$PURE" == "1" ]]; then
    bad "华为「纯净模式」已开启 —— APK 会被拦截"
    say "     → 设置 → 系统和更新 → 纯净模式 → 退出（${B}需登录华为账号${N}）"
  else
    warn "无法确认纯净模式状态（属性名随版本变化）"
    say "     → 请手动确认：设置 → 系统和更新 → 纯净模式 → 应为「已退出」"
    say "     → ${B}退出需要华为账号，老人常不记得密码，子女用自己账号登${N}"
  fi
fi

# ---------------------------------------------------------------- 闹钟
hdr "② 闹钟会不会响（核心功能）"

if (( SDK >= 33 )); then
  ok "API $SDK ≥ 33：可用 USE_EXACT_ALARM（normal 权限，装完即生效）"
elif (( SDK >= 31 )); then
  ok "API $SDK = 31/32：SCHEDULE_EXACT_ALARM 预授予，闹钟可用"
  warn "此机${B}永远暴露不出${N} Android 14+ 默认拒绝的问题 —— 必须另测一台 Android 14/15"
else
  ok "API $SDK < 31：无精确闹钟权限限制"
fi

# Doze 白名单
if $ADB shell dumpsys deviceidle whitelist 2>/dev/null | grep -qi "chiyaole"; then
  ok "已在电池优化白名单中"
else
  warn "不在电池优化白名单 —— 装机后必须手动加入，否则闹钟会被延迟或吞掉"
fi

# 厂商保活提示
hdr "③ 厂商保活（装机时必须手动完成）"
case "$(echo "$MANUF$BRAND" | tr 'A-Z' 'a-z')" in
  *huawei*|*honor*)
    say "  ${B}华为/荣耀/鸿蒙${N}"
    say "   1. 设置 → 应用和服务 → 应用启动管理 → 吃药了"
    say "      关闭「自动管理」，打开：自启动 / 关联启动 / 后台活动"
    say "   2. 设置 → 搜索「电池优化」→ 左上角选「所有应用」→ 吃药了 → 不允许"
    say "   3. 最近任务上滑 → 找到应用 → 下拉锁定" ;;
  *xiaomi*|*redmi*|*poco*)
    say "  ${B}小米/红米${N}"
    say "   1. 设置 → 应用设置 → 授权管理 → 自启动管理 → 允许"
    say "   2. 应用信息 → 省电策略 → 无限制"
    say "   3. 允许后台弹出界面" ;;
  *oppo*|*oneplus*|*realme*)
    say "  ${B}OPPO/一加${N}"
    say "   1. 设置 → 电池 → 应用耗电管理 → 允许后台运行"
    say "   2. 关闭「智能耗电保护」" ;;
  *vivo*|*iqoo*)
    say "  ${B}vivo${N}"
    say "   1. 设置 → 电池 → 后台耗电管理 → 允许后台高耗电"
    say "   2. 开启自启动" ;;
  *) say "  ${D}未识别厂商，参考技术规格 §4.2${N}" ;;
esac

# ---------------------------------------------------------------- 显示
hdr "④ 显示与字体（布局风险）"
FS=$($ADB shell settings get system font_scale 2>/dev/null | tr -d '\r')
[[ -z "$FS" || "$FS" == "null" ]] && FS="1.0"
DENS=$($ADB shell wm density 2>/dev/null | tr -d '\r')
SIZE=$($ADB shell wm size 2>/dev/null | tr -d '\r')
printf "  %s\n  %s\n" "$SIZE" "$DENS"
printf "  字体缩放 : %s\n" "$FS"

if awk "BEGIN{exit !($FS >= 1.3)}" 2>/dev/null; then
  warn "字体已放大到 ${FS}× —— ${B}必须逐屏验证按钮不被截断${N}"
else
  ok "字体缩放 ${FS}×"
  say "     ${D}提示：目标用户通常会把字体调到最大，请手动拉满后再测一遍${N}"
fi

# ---------------------------------------------------------------- 性能
hdr "⑤ 性能（冷启动风险）"
SOC=$(prop ro.board.platform)
HW=$(prop ro.hardware)
MEM=$($ADB shell cat /proc/meminfo 2>/dev/null | awk '/MemTotal/{printf "%.1f GB", $2/1048576}')
printf "  SoC      : %s / %s\n" "${SOC:-?}" "${HW:-?}"
printf "  内存     : %s\n" "${MEM:-?}"
say "  ${D}低端 SoC（如麒麟 710A）冷启动可能 1–3 秒${N}"
say "  ${D}→ 前台服务保温 + 先亮屏再播报 + 药盒图预缓存${N}"

# ---------------------------------------------------------------- 结论
hdr "结论"
if (( FATAL > 0 )); then
  printf "  ${R}${B}✗ 不兼容 —— 不要安装${N}（致命 %d 项，警告 %d 项）\n" "$FATAL" "$WARN"
  say "  → 走降级方案：大字用药表设为锁屏 + 子女端网页"
  exit 2
elif (( WARN > 0 )); then
  printf "  ${Y}${B}! 可以安装，但有 %d 项需要手动处理${N}\n" "$WARN"
  say "  → 按上面 ③ 的步骤逐条设置完，再做 72 小时闹钟测试"
  exit 1
else
  printf "  ${G}${B}✓ 全部通过${N}\n"
  exit 0
fi
