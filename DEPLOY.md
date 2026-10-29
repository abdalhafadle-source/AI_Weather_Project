# دليل النشر (Windows + VS Code)

الفكرة: GitHub Actions يشغّل النموذج كل ساعة ويحفظ الأمر في المستودع، وخدمة Render المجانية تعرض آخر أمر للـ ESP32.
كل شيء مجاني وبدون مفاتيح سرية.

## أ) بريد خاص لهذا المستودع فقط
حتى لا يظهر بريدك الحقيقي للناس، نستخدم بريد GitHub الخاص (noreply). في الطرفية داخل مجلد المشروع:

```
git init
git config user.email "287819978+abdalhafadle-source@users.noreply.github.com"
git config user.name "abdalhafadle-source"
```
(بدون `--global`، يعني يعمل لهذا المشروع فقط.)
للتأكد من أن البريد الخاص مفعّل: GitHub ← Settings ← Emails ← فعّل "Keep my email addresses private".
لا تكتب بريدك الحقيقي في أي ملف.

## ب) النشر على GitHub
1. في VS Code افتح Source Control (أيقونة الفروع) ← اكتب رسالة مثل `first version` ← Commit.
2. اضغط "Publish to GitHub" واختر **Public repository** باسم `hilla-pv-cleaner`.
   (أول مرة سيفتح VS Code المتصفح لتسجيل الدخول إلى GitHub — وافق على "Authorize".)
3. ملاحظة: مجلد `data/raw` (بغداد) لا يُرفع لأنه في `.gitignore`.

## ج) صلاحيات Actions وأول تشغيل
1. GitHub ← المستودع ← Settings ← Actions ← General ← Workflow permissions ← **Read and write permissions** ← Save.
2. تبويب Actions ← "hourly" ← Run workflow. بعد دقيقتين يجب أن تظهر علامة خضراء ويتحدث `output/command.json`.
3. بعدها يعمل تلقائياً كل ساعة. وكل يوم جمعة 02:00 بتوقيت بغداد يعمل "weekly_retrain" (يمكن تشغيله يدوياً أيضاً).

## د) Render
1. render.com ← New ← **Blueprint** ← اربط المستودع `hilla-pv-cleaner`.
2. الملف `render.yaml` فيه المتغيران جاهزان:
   - COMMAND_URL = https://raw.githubusercontent.com/abdalhafadle-source/hilla-pv-cleaner/main/output/command.json
   - LOG_URL = https://raw.githubusercontent.com/abdalhafadle-source/hilla-pv-cleaner/main/output/decision_log.csv
3. اضغط Deploy وانتظر حتى تصبح الحالة Live.

## هـ) الاختبار
- العنوان غالباً: `https://hilla-pv-cleaner.onrender.com` (يظهر في أعلى صفحة الخدمة في Render).
- `https://hilla-pv-cleaner.onrender.com/command` ← يجب أن يظهر JSON فيه `action`.
- `https://hilla-pv-cleaner.onrender.com/` ← صفحة الحالة وآخر 24 قراراً.
- وضع الأمان: يرجع الخادم `action: wait` مع `command_id: null` إذا كان الأمر أقدم من ساعة بعد `valid_until`،
  **وأمر `clean` لا يُرسَل أبداً بعد انتهاء `valid_until`** (حتى لو كانت ساعة الـ ESP32 غير مضبوطة).
- أول طلب بعد خمول قد يستغرق دقيقة (Render المجاني ينام).

## و) عقد الـ ESP32
- اسأل `/command` كل **14 دقيقة** (حتى لا ينام Render المجاني).
- مهلة HTTP **90 ثانية على الأقل** (الاستيقاظ بطيء).
- نفّذ فقط إذا: `action == "clean"` و`command_id` جديد لم يُنفَّذ سابقاً (احفظ آخر `command_id` نُفِّذ في ذاكرة الـ ESP32 — نفس الأمر يصل ~4 مرات خلال الساعة).
- فحص `valid_until` على الـ ESP32 اختياري (يحتاج ساعة مضبوطة عبر NTP) — الخادم يفحصه أصلاً.
- لا تشغّل المضخة أكثر من `max_duration_min` (الحد الأعلى 30 دقيقة).
- إذا فشل الاتصال أو الرد غير مفهوم: لا تفعل شيئاً.

المصدر: Open-Meteo.com (CC BY 4.0)؛ METAR: aviationweather.gov.
