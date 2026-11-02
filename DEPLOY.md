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
2. اضغط "Publish to GitHub" واختر **Public repository** (اسمه الحالي `AI_Weather_Project`).
   (أول مرة سيفتح VS Code المتصفح لتسجيل الدخول إلى GitHub — وافق على "Authorize".)
3. ملاحظة: مجلد `data/raw` (بغداد) لا يُرفع لأنه في `.gitignore`.

## ج) صلاحيات Actions وأول تشغيل
1. GitHub ← المستودع ← Settings ← Actions ← General ← Workflow permissions ← **Read and write permissions** ← Save.
2. تبويب Actions ← "hourly" ← Run workflow. بعد دقيقتين يجب أن تظهر علامة خضراء ويتحدث `output/command.json`.
3. بعدها يعمل تلقائياً كل ساعة. وكل يوم جمعة 02:00 بتوقيت بغداد يعمل "weekly_retrain" (يمكن تشغيله يدوياً أيضاً).

## د) الـ ESP32 يقرأ الأمر من GitHub مباشرة (بلا Render)
Render طلب بطاقة دفع، فاستغنينا عنه: GitHub ينشر الأمر على عنوان عام، والـ ESP32 يقرؤه مباشرة:
```
https://raw.githubusercontent.com/abdalhafadle-source/AI_Weather_Project/main/output/command.json
```
افتح هذا العنوان في المتصفح: يجب أن ترى JSON فيه `action` و `command_id` لساعة اليوم.

## هـ) عقد الـ ESP32 (مطبَّق في `esp32/pv_cleaner_client/`)
- يقرأ العنوان أعلاه كل **14 دقيقة** (الأمر يتجدد مرة كل ساعة تقريباً عند الدقيقة 7–25).
- يأخذ الوقت الصحيح من الإنترنت (NTP) ويرفض أي أمر **بعد `valid_until`** أو إذا لم تُضبط الساعة بعد.
- ينفّذ فقط إذا: `action == "clean"` و`command_id` جديد لم يُنفَّذ سابقاً (محفوظ في ذاكرة الـ ESP32 — نفس الأمر يُقرأ ~4 مرات خلال الساعة).
- لا يشغّل المضخة أكثر من `max_duration_min` (الحد الأعلى 30 دقيقة، مفروض داخل الـ ESP32).
- إذا فشل الاتصال أو الرد غير مفهوم: لا يفعل شيئاً.

## و) اختياري: سيرفر FastAPI وصفحة الحالة (للعرض في المناقشة)
`server/app.py` نفس النافذة لكن مع صفحة حالة. يمكن تشغيله على اللابتوب أثناء المناقشة:
```
pip install -r server/requirements.txt
set COMMAND_URL=https://raw.githubusercontent.com/abdalhafadle-source/AI_Weather_Project/main/output/command.json
set LOG_URL=https://raw.githubusercontent.com/abdalhafadle-source/AI_Weather_Project/main/output/decision_log.csv
cd server && uvicorn app:app --port 8000
```
ثم افتح http://localhost:8000 .

المصدر: Open-Meteo.com (CC BY 4.0)؛ METAR: aviationweather.gov.
