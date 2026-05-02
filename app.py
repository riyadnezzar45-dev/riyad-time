from flask import Flask, jsonify, request
from datetime import datetime, timedelta
import threading
import time
import requests
import json
import os

app = Flask(__name__)

# تكوين واجهات API الخاصة بك
ADD_API_URL = "https://riyad-add.vercel.app/add"
REMOVE_API_URL = "https://riyad-remove.vercel.app/remove"

# ملف التخزين
STORAGE_FILE = "uid_storage.json"

# ذاكرة مؤقتة لتخزين الـ UIDs ووقت انتهائها
uids_cache = {}
cache_lock = threading.Lock()
CLEANUP_INTERVAL = 60  # فحص كل 60 ثانية

def load_uids_from_file():
    """تحميل الـ UIDs من ملف التخزين"""
    global uids_cache
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                uids_cache = data
                print(f"✅ تم تحميل {len(uids_cache)} UID من الملف")
        except Exception as e:
            print(f"❌ خطأ في تحميل الملف: {e}")
            uids_cache = {}
    else:
        print("📁 لا يوجد ملف سابق، سيتم إنشاء ملف جديد")
        uids_cache = {}

def save_uids_to_file():
    """حفظ الـ UIDs في ملف التخزين"""
    try:
        with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(uids_cache, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"❌ خطأ في حفظ الملف: {e}")
        return False

def add_uid_to_api(uid: str, time_value: int = None, time_unit: str = None, permanent: bool = False):
    """إرسال طلب إضافة UID إلى واجهة /add"""
    params = [f"uid={uid}"]
    if permanent:
        params.append("permanent=true")
    else:
        if time_value and time_unit:
            params.append(f"time={time_value}")
            params.append(f"type={time_unit}")
    
    api_url = f"{ADD_API_URL}?" + "&".join(params)
    
    try:
        response = requests.get(api_url, timeout=10)
        return response.json(), response.status_code
    except Exception as e:
        return {"error": f"فشل الاتصال بـ API الإضافة: {str(e)}"}, 500

def delete_uid_from_api(uid: str) -> bool:
    """إرسال طلب حذف UID إلى واجهة /uid باستخدام المعامل uid"""
    url = f"{REMOVE_API_URL}?uid={uid}"
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            print(f"تم حذف {uid} بنجاح باستخدام: {url}")
            return True
        
        print(f"فشل حذف {uid}. استجابة الخادم: {response.status_code}")
        return False
    except Exception as e:
        print(f"خطأ في حذف {uid}: {e}")
        return False

def cleanup_expired_uids():
    """فحص وحذف الـ UIDs منتهية الصلاحية من الكاش ومن API الحذف"""
    while True:
        time.sleep(CLEANUP_INTERVAL)
        current_time = datetime.now()
        expired_uids = []
        
        with cache_lock:
            for uid, expiry_str in list(uids_cache.items()):
                if expiry_str == 'permanent':
                    continue
                try:
                    exp_time = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
                    if current_time > exp_time:
                        expired_uids.append(uid)
                except:
                    pass
        
        for uid in expired_uids:
            if delete_uid_from_api(uid):
                with cache_lock:
                    if uid in uids_cache:
                        del uids_cache[uid]
                        save_uids_to_file()  # حفظ التغييرات بعد الحذف
                print(f"✅ تم حذف الـ UID منتهي الصلاحية: {uid}")

# بدء خيط التنظيف التلقائي
cleanup_thread = threading.Thread(target=cleanup_expired_uids, daemon=True)
cleanup_thread.start()

# ============= أوامر API =============

@app.route('/add_uid', methods=['GET'])
def add_uid():
    """
    إضافة UID جديد - يرسل الطلب إلى https://riyad-add.vercel.app/add
    
    أمثلة:
    - /add_uid?uid=123&permanent=true          (دائم)
    - /add_uid?uid=123&time=5&type=days        (5 أيام)
    - /add_uid?uid=123&time=30&type=minutes    (30 دقيقة)
    - /add_uid?uid=123&time=2&type=hours       (2 ساعة)
    - /add_uid?uid=123&time=30&type=seconds    (30 ثانية)
    """
    uid = request.args.get('uid')
    permanent = request.args.get('permanent', 'false').lower() == 'true'
    time_value = request.args.get('time')
    time_unit = request.args.get('type')
    
    if not uid:
        return jsonify({'error': '❌ الرجاء إدخال uid'}), 400
    
    # تخزين وقت الإضافة لحساب الانتهاء لاحقاً
    current_time = datetime.now()
    
    if permanent:
        expiry_time = 'permanent'
        result, status = add_uid_to_api(uid, permanent=True)
    else:
        if not time_value or not time_unit:
            return jsonify({'error': '❌ الرجاء إدخال time و type'}), 400
        
        try:
            time_value = int(time_value)
        except ValueError:
            return jsonify({'error': '❌ الوقت يجب أن يكون رقماً'}), 400
        
        # حساب وقت الانتهاء للتخزين المؤقت
        time_units = {
            'seconds': timedelta(seconds=time_value),
            'minutes': timedelta(minutes=time_value),
            'hours': timedelta(hours=time_value),
            'days': timedelta(days=time_value),
            'months': timedelta(days=time_value * 30),
            'years': timedelta(days=time_value * 365)
        }
        
        if time_unit not in time_units:
            return jsonify({'error': 'نوع الوقت غير صالح. استخدم: seconds, minutes, hours, days, months, years'}), 400
        
        expiry_time = (current_time + time_units[time_unit]).strftime('%Y-%m-%d %H:%M:%S')
        result, status = add_uid_to_api(uid, time_value, time_unit)
    
    # تخزين في الكاش المؤقت والملف
    if status == 200:
        with cache_lock:
            uids_cache[uid] = expiry_time
            save_uids_to_file()  # حفظ التغييرات بعد الإضافة
        return jsonify({
            'message': '✅ تم إضافة UID بنجاح',
            'uid': uid,
            'expires_at': expiry_time if not permanent else 'لا ينتهي أبداً',
            'time_unit': time_unit if not permanent else 'permanent',
            'time_value': time_value if not permanent else None,
            'api_response': result
        }), status
    else:
        return jsonify(result), status

@app.route('/remaining_time/<string:uid>', methods=['GET'])
def remaining_time(uid):
    """معرفة الوقت المتبقي لـ UID"""
    with cache_lock:
        expiry = uids_cache.get(uid)
    
    if not expiry:
        return jsonify({'error': '❌ لم يتم العثور على هذا الـ UID'}), 404
    
    if expiry == 'permanent':
        return jsonify({
            'uid': uid,
            'status': 'permanent',
            'message': 'هذا الـ UID دائم ولا ينتهي أبداً'
        })
    
    try:
        exp_time = datetime.strptime(expiry, '%Y-%m-%d %H:%M:%S')
        now = datetime.now()
        
        if now > exp_time:
            return jsonify({'error': '⏰ هذا الـ UID قد انتهى صلاحيته'}), 400
        
        remaining = exp_time - now
        days = remaining.days
        hours, rem = divmod(remaining.seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        
        return jsonify({
            'uid': uid,
            'expires_at': expiry,
            'time_remaining': f"{days} أيام, {hours} ساعات, {minutes} دقائق, {seconds} ثوانٍ",
            'details': {
                'days': days,
                'hours': hours,
                'minutes': minutes,
                'seconds': seconds
            }
        })
    except:
        return jsonify({'error': 'خطأ في تنسيق الوقت'}), 500

@app.route('/delete_uid/<string:uid>', methods=['GET'])
def delete_uid(uid):
    """حذف UID يدوياً"""
    if delete_uid_from_api(uid):
        with cache_lock:
            uids_cache.pop(uid, None)
            save_uids_to_file()  # حفظ التغييرات بعد الحذف
        return jsonify({'message': f'✅ تم حذف الـ UID {uid}'})
    else:
        return jsonify({'error': f'❌ فشل حذف الـ UID {uid} - تأكد من صحة الرابط'}), 500

@app.route('/list_uids', methods=['GET'])
def list_uids():
    """عرض جميع الـ UIDs المخزنة"""
    with cache_lock:
        uids_list = list(uids_cache.keys())
        uids_details = {}
        for uid, expiry in uids_cache.items():
            uids_details[uid] = {
                'expiry': expiry,
                'is_permanent': expiry == 'permanent'
            }
    return jsonify({
        'total': len(uids_list), 
        'uids': uids_list,
        'details': uids_details
    })

@app.route('/backup', methods=['GET'])
def backup_data():
    """عمل نسخة احتياطية من البيانات"""
    with cache_lock:
        backup_data = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_uids': len(uids_cache),
            'data': uids_cache.copy()
        }
    
    try:
        backup_file = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)
        
        return jsonify({
            'message': '✅ تم إنشاء النسخة الاحتياطية',
            'file': backup_file,
            'total_uids': len(uids_cache)
        })
    except Exception as e:
        return jsonify({'error': f'فشل إنشاء النسخة: {e}'}), 500

@app.route('/')
def home():
    return jsonify({
        'service': '🚀 UID Manager',
        'storage_file': STORAGE_FILE,
        'add_api': ADD_API_URL,
        'remove_api': REMOVE_API_URL,
        'supported_time_units': ['seconds', 'minutes', 'hours', 'days', 'months', 'years'],
        'commands': {
            'add_permanent': '/add_uid?uid=ID&permanent=true',
            'add_seconds': '/add_uid?uid=ID&time=30&type=seconds',
            'add_minutes': '/add_uid?uid=ID&time=5&type=minutes',
            'add_hours': '/add_uid?uid=ID&time=2&type=hours',
            'add_days': '/add_uid?uid=ID&time=5&type=days',
            'add_months': '/add_uid?uid=ID&time=1&type=months',
            'add_years': '/add_uid?uid=ID&time=1&type=years',
            'check': '/remaining_time/ID',
            'delete': '/delete_uid/ID',
            'list': '/list_uids',
            'backup': '/backup'
        }
    })

if __name__ == '__main__':
    # تحميل البيانات المحفوظة عند بدء التشغيل
    load_uids_from_file()
    
    print("\n" + "="*60)
    print("🚀 UID MANAGER - مع حفظ البيانات في ملف")
    print("="*60)
    print(f"\n📁 ملف التخزين: {STORAGE_FILE}")
    print(f"📡 واجهة الإضافة: {ADD_API_URL}")
    print(f"📡 واجهة الحذف: {REMOVE_API_URL}")
    print(f"\n📊 تم تحميل {len(uids_cache)} UID من الملف")
    print("\n📋 أوامر الإضافة:")
    print("   /add_uid?uid=123&permanent=true        (دائم)")
    print("   /add_uid?uid=123&time=30&type=seconds  (30 ثانية)")
    print("   /add_uid?uid=123&time=5&type=minutes   (5 دقائق)")
    print("   /add_uid?uid=123&time=2&type=hours     (2 ساعة)")
    print("   /add_uid?uid=123&time=5&type=days      (5 أيام)")
    print("\n📋 أوامر أخرى:")
    print("   /remaining_time/123")
    print("   /delete_uid/123")
    print("   /list_uids")
    print("   /backup                           (نسخة احتياطية)")
    print("\n" + "="*60)
    app.run(host='0.0.0.0', port=50022, debug=False)
