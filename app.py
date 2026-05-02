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
                return True
        except Exception as e:
            print(f"❌ خطأ في تحميل الملف: {e}")
            uids_cache = {}
            return False
    else:
        print("📁 لا يوجد ملف سابق، سيتم إنشاء ملف جديد")
        uids_cache = {}
        return False

def save_uids_to_file():
    """حفظ الـ UIDs في ملف التخزين"""
    try:
        with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(uids_cache, f, ensure_ascii=False, indent=2)
        print(f"💾 تم حفظ {len(uids_cache)} UID في الملف")
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
        print(f"📤 إرسال طلب إضافة {uid} إلى API")
        return response.json(), response.status_code
    except Exception as e:
        print(f"❌ فشل الاتصال بـ API الإضافة: {e}")
        return {"error": f"فشل الاتصال بـ API الإضافة: {str(e)}"}, 500

def delete_uid_from_api(uid: str) -> bool:
    """إرسال طلب حذف UID إلى واجهة /remove"""
    url = f"{REMOVE_API_URL}?uid={uid}"
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            print(f"🗑️ تم حذف {uid} بنجاح من API")
            return True
        else:
            print(f"⚠️ فشل حذف {uid} من API. الحالة: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ خطأ في حذف {uid} من API: {e}")
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
                        print(f"⏰ وجدت UID منتهي الصلاحية: {uid}")
                except Exception as e:
                    print(f"⚠️ خطأ في معالجة {uid}: {e}")
                    pass
        
        # حذف الـ UIDs منتهية الصلاحية
        for uid in expired_uids:
            if delete_uid_from_api(uid):
                with cache_lock:
                    if uid in uids_cache:
                        del uids_cache[uid]
                        save_uids_to_file()
                print(f"✅ تم حذف الـ UID منتهي الصلاحية: {uid}")
            else:
                print(f"❌ فشل حذف {uid} من API، سيتم المحاولة مرة أخرى لاحقاً")

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
    
    current_time = datetime.now()
    
    if permanent:
        expiry_time = 'permanent'
        result, status = add_uid_to_api(uid, permanent=True)
        time_display = "دائم"
    else:
        if not time_value or not time_unit:
            return jsonify({'error': '❌ الرجاء إدخال time و type'}), 400
        
        try:
            time_value = int(time_value)
            if time_value <= 0:
                return jsonify({'error': '❌ الوقت يجب أن يكون أكبر من 0'}), 400
        except ValueError:
            return jsonify({'error': '❌ الوقت يجب أن يكون رقماً'}), 400
        
        # حساب وقت الانتهاء
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
        time_display = f"{time_value} {time_unit}"
    
    # تخزين في الكاش والملف
    if status == 200:
        with cache_lock:
            uids_cache[uid] = expiry_time
            save_uids_to_file()
        
        return jsonify({
            'success': True,
            'message': '✅ تم إضافة UID بنجاح',
            'uid': uid,
            'expires_at': expiry_time if not permanent else 'لا ينتهي أبداً',
            'duration': time_display,
            'api_response': result
        }), status
    else:
        return jsonify({
            'success': False,
            'error': result
        }), status

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
            'message': '✨ هذا الـ UID دائم ولا ينتهي أبداً'
        })
    
    try:
        exp_time = datetime.strptime(expiry, '%Y-%m-%d %H:%M:%S')
        now = datetime.now()
        
        if now > exp_time:
            return jsonify({
                'error': '⏰ هذا الـ UID قد انتهى صلاحيته',
                'expired_at': expiry
            }), 400
        
        remaining = exp_time - now
        days = remaining.days
        hours, rem = divmod(remaining.seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        
        # حساب إجمالي الثواني
        total_seconds = int(remaining.total_seconds())
        
        return jsonify({
            'uid': uid,
            'status': 'active',
            'expires_at': expiry,
            'time_remaining': f"{days} أيام, {hours} ساعات, {minutes} دقائق, {seconds} ثوانٍ",
            'total_seconds': total_seconds,
            'details': {
                'days': days,
                'hours': hours,
                'minutes': minutes,
                'seconds': seconds
            }
        })
    except Exception as e:
        return jsonify({'error': f'خطأ في تنسيق الوقت: {str(e)}'}), 500

@app.route('/delete_uid/<string:uid>', methods=['GET', 'DELETE'])
def delete_uid(uid):
    """حذف UID يدوياً"""
    with cache_lock:
        if uid not in uids_cache:
            return jsonify({'error': f'❌ الـ UID {uid} غير موجود'}), 404
    
    if delete_uid_from_api(uid):
        with cache_lock:
            uids_cache.pop(uid, None)
            save_uids_to_file()
        return jsonify({
            'success': True,
            'message': f'✅ تم حذف الـ UID {uid} بنجاح'
        })
    else:
        return jsonify({
            'success': False,
            'error': f'❌ فشل حذف الـ UID {uid} من API'
        }), 500

@app.route('/list_uids', methods=['GET'])
def list_uids():
    """عرض جميع الـ UIDs المخزنة"""
    with cache_lock:
        uids_list = list(uids_cache.keys())
        uids_details = {}
        
        for uid, expiry in uids_cache.items():
            if expiry == 'permanent':
                uids_details[uid] = {
                    'expiry': 'permanent',
                    'is_permanent': True,
                    'status': 'دائم'
                }
            else:
                try:
                    exp_time = datetime.strptime(expiry, '%Y-%m-%d %H:%M:%S')
                    now = datetime.now()
                    if now > exp_time:
                        status = 'منتهي'
                    else:
                        remaining = exp_time - now
                        status = f"ينتهي بعد {remaining.days} أيام"
                except:
                    status = 'غير معروف'
                
                uids_details[uid] = {
                    'expiry': expiry,
                    'is_permanent': False,
                    'status': status
                }
    
    return jsonify({
        'total': len(uids_list),
        'uids': uids_list,
        'details': uids_details,
        'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/cleanup_now', methods=['GET'])
def cleanup_now():
    """تنظيف فوري للـ UIDs منتهية الصلاحية"""
    print("🧹 بدء التنظيف الفوري...")
    
    current_time = datetime.now()
    expired_uids = []
    
    with cache_lock:
        for uid, expiry_str in list(uids_cache.items()):
            if expiry_str != 'permanent':
                try:
                    exp_time = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
                    if current_time > exp_time:
                        expired_uids.append(uid)
                except:
                    pass
    
    deleted = []
    for uid in expired_uids:
        if delete_uid_from_api(uid):
            with cache_lock:
                if uid in uids_cache:
                    del uids_cache[uid]
                    deleted.append(uid)
    
    if deleted:
        save_uids_to_file()
    
    return jsonify({
        'message': f'🧹 تم تنظيف {len(deleted)} UID منتهي الصلاحية',
        'deleted_uids': deleted,
        'remaining_uids': len(uids_cache)
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
            'success': True,
            'message': '✅ تم إنشاء النسخة الاحتياطية',
            'file': backup_file,
            'total_uids': len(uids_cache)
        })
    except Exception as e:
        return jsonify({'error': f'فشل إنشاء النسخة: {e}'}), 500

@app.route('/stats', methods=['GET'])
def get_stats():
    """إحصائيات عن الـ UIDs"""
    with cache_lock:
        permanent = sum(1 for v in uids_cache.values() if v == 'permanent')
        temporary = len(uids_cache) - permanent
        expired = 0
        
        now = datetime.now()
        for expiry in uids_cache.values():
            if expiry != 'permanent':
                try:
                    if datetime.strptime(expiry, '%Y-%m-%d %H:%M:%S') < now:
                        expired += 1
                except:
                    pass
    
    return jsonify({
        'total_uids': len(uids_cache),
        'permanent_uids': permanent,
        'temporary_uids': temporary,
        'expired_uids': expired,
        'active_uids': temporary - expired,
        'storage_file': STORAGE_FILE,
        'cleanup_interval': f"{CLEANUP_INTERVAL} ثانية"
    })

@app.route('/')
def home():
    return jsonify({
        'service': '🚀 UID Manager - نظام إدارة الـ UIDs',
        'version': '2.0',
        'storage_file': STORAGE_FILE,
        'add_api': ADD_API_URL,
        'remove_api': REMOVE_API_URL,
        'supported_time_units': ['seconds', 'minutes', 'hours', 'days', 'months', 'years'],
        'auto_cleanup': f'كل {CLEANUP_INTERVAL} ثانية',
        'commands': {
            'إضافة UID': {
                'دائم': '/add_uid?uid=ID&permanent=true',
                'ثواني': '/add_uid?uid=ID&time=30&type=seconds',
                'دقائق': '/add_uid?uid=ID&time=5&type=minutes',
                'ساعات': '/add_uid?uid=ID&time=2&type=hours',
                'أيام': '/add_uid?uid=ID&time=5&type=days',
                'شهور': '/add_uid?uid=ID&time=1&type=months',
                'سنوات': '/add_uid?uid=ID&time=1&type=years'
            },
            'التحقق': {
                'الوقت المتبقي': '/remaining_time/ID'
            },
            'الحذف': {
                'يدوي': '/delete_uid/ID'
            },
            'الإدارة': {
                'قائمة UIDs': '/list_uids',
                'تنظيف فوري': '/cleanup_now',
                'نسخة احتياطية': '/backup',
                'إحصائيات': '/stats'
            }
        }
    })

if __name__ == '__main__':
    # تحميل البيانات المحفوظة عند بدء التشغيل
    load_uids_from_file()
    
    print("\n" + "="*70)
    print("🚀 UID MANAGER - نظام إدارة الـ UIDs مع تخزين محلي")
    print("="*70)
    print(f"\n📁 ملف التخزين: {STORAGE_FILE}")
    print(f"📡 واجهة الإضافة: {ADD_API_URL}")
    print(f"📡 واجهة الحذف: {REMOVE_API_URL}")
    print(f"⏰ تنظيف تلقائي: كل {CLEANUP_INTERVAL} ثانية")
    print(f"\n📊 تم تحميل {len(uids_cache)} UID من الملف")
    print("\n📋 الأوامر المتاحة:")
    print("   ➕ /add_uid?uid=123&permanent=true")
    print("   ➕ /add_uid?uid=123&time=30&type=seconds")
    print("   🔍 /remaining_time/123")
    print("   🗑️ /delete_uid/123")
    print("   📋 /list_uids")
    print("   🧹 /cleanup_now")
    print("   💾 /backup")
    print("   📊 /stats")
    print("\n" + "="*70)
    print("🌐 الخادم يعمل على http://0.0.0.0:50022")
    print("="*70 + "\n")
    
    app.run(host='0.0.0.0', port=50022, debug=False)
