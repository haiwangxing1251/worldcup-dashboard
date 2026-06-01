#!/usr/bin/env python3
"""
为 docs/index.html 中的竞猜按钮添加事件委托 JS
完全规避 Python 字符串转义问题
"""
import re, sys

HTML = "docs/index.html"
with open(HTML, "r", encoding="utf-8") as f:
    content = f.read()

# 检查是否已经注入过
if "guess-delegate" in content:
    print("[OK] Event delegation JS already exists, skipping")
    sys.exit(0)

# 在 </script> 前注入事件委托代码
# 找到今日比赛模块对应的 </script>
# 策略：在 window.wcGuessMatch 定义之后、第一个 </script> 之前插入
delegate_js = r"""
// 竞猜按钮事件委托 (guess-delegate)
document.addEventListener('click', function(e) {
  var btn = e.target.closest && e.target.closest('.guess-btn');
  if (!btn) return;
  var h = btn.dataset.home, hc = btn.dataset.homeCn;
  var a = btn.dataset.away, ac = btn.dataset.awayCn;
  var g = btn.dataset.guess;
  if (h && a && g && window.wcGuessMatch) {
    window.wcGuessMatch(h, hc, a, ac, g);
  }
});
"""

# 在 window.wcGuessMatch 函数定义之后插入
# 匹配模式：window.wcGuessMatch = function ... }};  后面插入
pattern = r"(window\.wcGuessMatch\s*=\s*function\s*\([^)]*\)\s*\{[^}]*\}\s*;)"
replacement = r"\1" + delegate_js
new_content = re.sub(pattern, replacement, content, count=1)

if new_content == content:
    print("[WARN] window.wcGuessMatch not found, trying </script>...")
    # 找到今日比赛模块所在的 </script>
    pos = content.find("TODAY_INITIAL")
    if pos < 0:
        print("[ERR] TODAY_INITIAL not found, abort")
        sys.exit(1)
    end_script = content.find("</script>", pos)
    if end_script < 0:
        print("[ERR] Corresponding </script> not found, abort")
        sys.exit(1)
    new_content = content[:end_script] + delegate_js + "\n" + content[end_script:]
else:
    print("[OK] Inserted event delegation JS after window.wcGuessMatch")

with open(HTML, "w", encoding="utf-8") as f:
    f.write(new_content)

print("[OK] docs/index.html updated with guess button event delegation")
