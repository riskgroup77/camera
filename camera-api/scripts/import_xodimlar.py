# -*- coding: utf-8 -*-
"""Institut xodimlarini tizimga ommaviy kiritish.

MAQSAD. Kadrlar bo'limining ro'yxatidagi har bir xodim tizimda o'z
qatoriga ega bo'lishi va JSHSHIR raqami orqali ochiq sahifada o'zini
biometrik ro'yxatdan o'tkaza olishi kerak. Ro'yxatdan bironta xodim
qolib ketmasligi shart, shuning uchun skript oxirida import qilingan
qatorlar soni bazadan qayta sanab tekshiriladi.

ISHGA TUSHIRISH (server, konteyner ichida):

    docker compose exec -T api python scripts/import_xodimlar.py

Faqat ko'rish uchun (bazaga hech narsa yozmaydi):

    docker compose exec -T api python scripts/import_xodimlar.py --dry-run

XAVFSIZLIK. Skript IDEMPOTENT — istalgan marta qayta ishga tushirilishi
mumkin:

  * JSHSHIR bo'yicha mavjud qator TOPILSA — faqat bo'sh maydonlari
    to'ldiriladi (ism, fakultet, bo'lim). Biometrik holat, yuz vektori
    va fotosurat HECH QACHON o'zgartirilmaydi. Ya'ni allaqachon yuzini
    tasdiqlagan xodim skriptni qayta ishga tushirish tufayli tasdig'ini
    yo'qotmaydi.
  * Topilmasa — yangi qator yaratiladi, biometrik holat "yoq" bilan.
  * Fakultetlar ham JSHSHIR kabi nom bo'yicha solishtiriladi va faqat
    mavjud bo'lmaganda yaratiladi.

MA'LUMOT MANBASI. Kadrlar bo'limi bergan "xodimlar.xlsx" fayli. Ma'lumot
skript ichiga yozilgan — bu ataylab: serverda Excel o'qish kutubxonasi
talab qilinmaydi, fayl versiyalari chalkashmaydi va import qachon nima
qilgani git tarixida ko'rinib turadi.

ISMLAR. Manba faylda ismlar bosh harflar bilan yozilgan (QAYUMOV
G'ANISHER). Bu yerda ular o'qiladigan holga keltirilgan va
"Familiya Ism Otasining ismi" tartibida birlashtirilgan — panelda va
hodisa yozuvlarida aynan shu ko'rinishda chiqadi.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter

# Skript "python scripts/import_xodimlar.py" tarzida ishga tushiriladi,
# ya'ni Python yo'liga scripts/ papkasi tushadi, loyiha ildizi emas —
# natijada "app" paketi topilmaydi. Ildizni o'zimiz qo'shamiz.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import SessionLocal
from app.models import Faculty, StudentStaff

# Xodimning tizimdagi turi. Bu ro'yxatda faqat xodimlar bor —
# talabalar alohida ro'yxat bilan kiritiladi.
PERSON_TYPE = "xodim"

# Fakulteti ko'rsatilmagan xodim (rektorat, texnik bo'limlar, xo'jalik
# xizmati) — ular ham ro'yxatga kiradi, faqat fakultetsiz. Ularni
# tashlab ketish "hech qaysi xodim qolib ketmasin" talabini buzardi.
NO_FACULTY = ""

# (JSHSHIR, F.I.SH., fakultet, kafedra yoki bo'lim)
XODIMLAR: list[tuple[str, str, str, str]] = [
    ('30302654150047', "Qayumov G'anisher Olimovich", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('52408017060030', "Baxromov Abdujalil Xaydarali o'g'li", '', "Texnik qo'llab-quvvatlash bo'limi"),
    ('31104986890056', "Sotqinov Bahriddinxo'ja Bahromxo'ja o'g'li", '', "Ma'lumotlar ba'zasi bo'limi (Back office)"),
    ('32503727010024', 'Xudayarov Shuxratjon Rustamovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('31308807040015', 'Xabibullayev Fayzulla Nabibullayevich', 'Xalqaro fakultet', 'Gistologiya va biologiya'),
    ('30901944190013', "Mahamadaliyev Azizjon Shovkat o'g'li", 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('42406804330062', 'Quzibayeva Zarifaxon Axmadjonovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('30101664330023', 'Sarimsaqov Mahamadjalol Isakjonovich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('42610774220018', 'Yuldasheva Kamolatxon Xashimovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('32002976890024', 'Dhage Shivprasad Sanjay', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('30506944160037', "Aliyev Ulug'bek Azamjon o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Mikrobiologiya, virusologiya va immunologiya'),
    ('40108996930058', "Eraliyeva Madina Ro'zimat qizi", 'Xalqaro fakultet', 'Fiziologiya'),
    ('30505644310014', 'Umarov Yusup Yunusovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('31909824310042', 'Somonov Boris Viktorovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('30210864330051', 'Ergashev Rustam Madaminovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('62209016960041', 'Abdunabiyeva Gulsanam Bekzodjon qizi', 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('40803966900058', 'Xomidova Gulsanamxon Farxodjon qizi', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Mikrobiologiya, virusologiya va immunologiya'),
    ('32112966960049', "Mahmudov Ulug'bek Ilhomjon o'g'li", 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('32202977020046', "Karimov Nurullo Xabibullo-o'g'li", 'Davolash ishi fakulteti', 'Umumiy jarrohlik'),
    ('41905954270088', 'Abidova Munojatxon Dilshodjon qizi', 'Pediatriya fakulteti', 'Pediatriya-2'),
    ('51903047040058', "Valiyev Xoshimjon Latifjon o'g'li", '', "Texnik qo'llab-quvvatlash bo'limi"),
    ('41307941330061', 'Kodirova Muxabbatxon Matkarim Kizi', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('41010957040032', 'Egamberdiyeva Gulchexraxon Sulton qizi', 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('42509767040042', 'Ruzibayeva Yorkinoy Ravshanovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('40511807040017', 'Shadmanova Nilufar Baxtiyarovna', '', 'Xisobxona'),
    ('32706944200010', "Xolmatov Muslimbek Toxirjon o'g'li", 'Davolash ishi fakulteti', 'Fakultet va gospital jarrohlik'),
    ('42105707040013', 'Tairova Lobarxon Yadgarovna', '', '1-talabalar turar joyi'),
    ('40510804250146', 'Abdurazakova Iqbolxon Abduraxmonovna', 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('40908996900031', 'Ixtiyorova Madinabonu Abdusalom qizi', 'Xalqaro fakultet', "O'zbek va xorijiy tillar"),
    ('30405724210040', 'Yulchiyev Raximjon Sattorovich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('31209986910040', "Raxmonberdiyev Islombek Xayrullo-o'g'li", '', "O'qitishning texnik vositalari bo'limi"),
    ('31103964220034', "Rahmonov Ilhomjon Ikromjon o'g'li", 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('41104824220035', "Noraliyeva Ma'muraxon Azimovna", '', 'Pediatriya fakulteti'),
    ('30204724270030', "O'rinboyev Abdug'ani Eminjon o'g'li", '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('43006977040033', 'Abduqaxhorova Chamanxon Shavkatjon qizi', 'Xalqaro fakultet', 'Gistologiya va biologiya'),
    ('43008814270061', 'Usupova Nargizaxon Yaminjonovna', '', "Fuqaro va mehnat muxofazasi bo'limi"),
    ('52803035880015', "Tursunaliyev Farxodjon To'lqinali o'g'li", '', "Magistratura bo'limi"),
    ('40501737040034', 'Mamasidiqova Sanoatxon Anvarbekovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('41007817040037', 'Dehqonova Yorqinoy Xabibullayevna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('32209787040015', 'Abdujabborov Iqboljon Xasanovich', '', "Axborot xavfsizligini ta'minlash bo'limi"),
    ('33009861150013', 'Ashurov Dilshod Davlatovich', 'Pediatriya fakulteti', 'Dermatovenerologiya va allergologiya'),
    ('42305944310018', 'Abdullazizova Umidaxon Saloxiddin qizi', 'Pediatriya fakulteti', 'Nevrologiya va psixiatriya'),
    ('40506697040030', 'Umarova Zulxumor Tulanovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('40806934220019', "Ne'matova Muattarxon Ilxomjon qizi", 'Pediatriya fakulteti', 'Nevrologiya va psixiatriya'),
    ('31703907040015', 'Shakirov Ruslan Radikovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('40809914330074', 'Isroilova Fotimaxon Usmonaliyevna', '', '2-Talabalar turar joyi'),
    ('40510844290027', 'Mirzaraximova Nodira Saminovna', 'Malaka oshirish va qayta tayyorlash fakulteti', 'Vrachlar malakasini oshirish va qayta tayyorlash kafedrasi'),
    ('41811854330022', 'Raxmanova Dilorom Xolmatovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('31007854220099', 'Valitov Elyor Akimovich', '', 'Davolash ishi fakulteti'),
    ('30304997010068', "Akbarov Abdulxamid Adxamjon o'g'li", 'Xalqaro fakultet', 'Gistologiya va biologiya'),
    ('30512907040014', "Mirxalilov Mirqobil Mirmuxsinjon o'g'li", '', 'Xisobxona'),
    ('42411976940056', 'Boynazarova Zilolaxon Lochinbek qizi', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Preventiv tibbiyot asoslari, jamoat salomatligi, jismoniy tarbiya va sport'),
    ('31305954270047', "Saydaxmedov Zuxriddin Ibroximjon o'g'li", 'Davolash ishi fakulteti', "Terapiya yo'nalishidagi fanlar (UASH)"),
    ('40606904140095', "Abdullayeva O'g'iloy Yakubovna", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('30805944230020', "Boqijonov Farrux Azizjon o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('41209934190020', 'Anvarova Zilolaxon Qosimjon qizi', 'Pediatriya fakulteti', 'Pediatriya'),
    ('30909767070013', 'Yuldashev Muzaffar Mamirovich', '', "O'quv metodik ta'minot bo'limi"),
    ('62207007010023', 'Raximova Xushnoza Shoirjon qizi', 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('32403876940019', 'Abdusalimov Sardorbek Abdullayevich', 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('32007894150021', 'Madolimov Abdubannop Muxammadjonovich', 'Davolash ishi fakulteti', 'Travmatologiya va ortopediya'),
    ('33103934210025', "Xaydarov Axrorjon G'ayratjon o'g'li", '', 'Pediatriya fakulteti'),
    ('41212777040025', 'Alimova Umida Alimovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('30301694310022', 'Kuznetsov Dmitriy Aleksandrovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('30812914310101', "Zokirov Muzaffar Muxtarali o'g'li", 'Pediatriya fakulteti', 'Nevrologiya va psixiatriya'),
    ('42606786890017', "Jumanova Barno G'aniyevna", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('32003804180058', 'Umarov Sherzodjon Usmonovich', 'Xalqaro fakultet', 'Ijtimoiy fanlar'),
    ('42207797040037', 'Xamrayeva Matluba Abralovna', '', 'Pediatriya fakulteti'),
    ('30510957020040', "Qodirov Abubakir Rashodjon-o'g'li", '', "O'quv metodik ta'minot bo'limi"),
    ('42204834210053', 'Doniyarova Firuza Xalimjonovna', '', "Reja-moliya bo'limi"),
    ('42601894310044', 'Babaxodjayeva Safura Valiyevna', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('30305854310042', 'Azimov Sodikjon Muradovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('42402964270022', "G'ayratjonova Fotimaxon G'ofurjon qizi", 'Davolash ishi fakulteti', "Terapiya yo'nalishidagi fanlar (UASH)"),
    ('42311634130015', 'Davranova Poraxotxon', '', 'Axborot-resurs markazi'),
    ('42208694290013', 'Egamberdiyeva Gulnoraxon Nematovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('41212967040013', 'Abdujapparova Naziraxon Erikli qizi', 'Davolash ishi fakulteti', 'Akusherlik va ginekologiya'),
    ('30401977010035', "Karimjonov Farruxjon Farxodjon o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Mikrobiologiya, virusologiya va immunologiya'),
    ('42506737040011', 'Azamatova Natalya Vladimirovna', '', 'Xisobxona'),
    ('40708787040070', 'Tadjibayeva Dilafruz Raxmonberdiyevna', 'Xalqaro fakultet', 'Gistologiya va biologiya'),
    ('32512874310028', 'Alimov Farrux Farxodovich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('30505627040017', 'Xolmatov Shaxobidin Jumabayevich', 'Xalqaro fakultet', 'Ijtimoiy fanlar'),
    ('42608884310118', 'Alimbekova Xavas Normatovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('32910894330062', "Dadajonov Ahror Kamoliddin o'g'li", '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('30412594140014', "Yusupov A'zamjon Abdulladjanovich", 'Xalqaro fakultet', 'Ijtimoiy fanlar'),
    ('32012704140022', "Muslimov G'anijon Inatullayevich", 'Pediatriya fakulteti', 'Pediatriya'),
    ('41211994110012', 'Kamolova Barno Baxodir qizi', 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('30801954270016', "Isaqov Sobirjon Rahmatjon o'g'li", '', 'Davolash ishi fakulteti'),
    ('40107944340017', 'Karimova Madinabonu Ilxomjon qizi', 'Xalqaro fakultet', 'Lotin tili, pedagogika va psixologiya'),
    ('40701924310010', 'Xodjayeva Diyora Baxtiyorovna', '', 'Vivariylar'),
    ('32110754150012', 'Xaitov Ravshan Raxmatillayevich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Preventiv tibbiyot asoslari, jamoat salomatligi, jismoniy tarbiya va sport'),
    ('40212864310050', 'Urinova Nodira Shavkatovna', 'Xalqaro fakultet', 'Lotin tili, pedagogika va psixologiya'),
    ('40809966940047', 'Madraximova Nigoraxon Ravshanbek qizi', 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('40710954310022', 'Koldasheva Moxiraxon Xatamjon qizi', 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('41309976900020', 'Axmadjonova Shahlo Valijon qizi', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('32510834190035', 'Xojimatov Xusnidin Odilovich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', "Ovqatlanish, bolalar va o'smirlar gigiyenasi"),
    ('31702927070017', 'Axmadaliyev Shoxrux Shuxratovich', 'Pediatriya fakulteti', 'Pediatriya-2'),
    ('30112977060020', "Muxammadjonov Oqilbek Mirzoulug'bek o'g'li", 'Davolash ishi fakulteti', 'Ichki kasalliklar propedevtikasi'),
    ('62705055890025', 'Isroiljanova Maxliyoxon Baxrom qizi', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('42108804330034', 'Djanbekova Ozodaxon Usmonaliyevna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('41308817070010', 'Axmadjonova Sanobarxon Raxmatovna', '', '3-talabalar turar joyi'),
    ('42903744310054', 'Xalbekova Dilfuza Maxmudovna', '', 'Pediatriya fakulteti'),
    ('32201941110048', "Jo'rayev Aziz Turob o'g'li", 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('96100132506089', 'Mullachery Kamalon Rohith Krishnan', 'Davolash ishi fakulteti', 'Fakultet va gospital jarrohlik'),
    ('42606654130010', 'Suyarkulova Madxiya Erkinovna', 'Davolash ishi fakulteti', 'Akusherlik va ginekologiya'),
    ('32412987010090', "Oxunjonov Toxirmalik Abdumalik o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('32603954270078', "Saminov Tohirbek To'lqinjon o'g'li", 'Pediatriya fakulteti', 'Urologiya va onkologiya'),
    ('32009977040025', "Jo'rayev Umarxon Ulug'bek o'g'li", 'Davolash ishi fakulteti', "Terapiya yo'nalishidagi fanlar (UASH)"),
    ('41602884310078', 'Axmedova Yelena Aleksandrovna', 'Pediatriya fakulteti', 'Pediatriya'),
    ('31106697040018', 'Mullayev Rustam Gafurovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('32002875050017', 'Valiyev Xusan Toxirovich', 'Pediatriya fakulteti', 'Urologiya va onkologiya'),
    ('42604887070013', 'Saiyburxonova Shaxnoza Muydinovna', '', "Texnik qo'llab-quvvatlash bo'limi"),
    ('31012912130049', "Abdullayev G'oyibsher Abdulxamidovich", '', 'Pediatriya fakulteti'),
    ('30212907030021', 'Sakkizboyev Ismoiljon Alijonovich', 'Davolash ishi fakulteti', 'Fakultet va gospital jarrohlik'),
    ('32406724310019', 'Mamadjanov Rustam Ergashevich', 'Davolash ishi fakulteti', "Terapiya yo'nalishidagi fanlar (UASH)"),
    ('62106035090020', 'Sadirova Nargizaxon Umarali qizi', 'Xalqaro fakultet', 'Ijtimoiy fanlar'),
    ('30208934340024', "Nazirxujayev Fozilxon Anvarxon o'g'li", 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('31706986970031', "Hakimov Xatamjon Yo'ldoshali o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('40405797030023', 'Qosimova Mohigul Azimjonovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('61002017040014', 'Nomonova Shaxnozaxon Muhammadjon qizi', 'Xalqaro fakultet', 'Gistologiya va biologiya'),
    ('32801986940077', "Ikromiy Arslonbek Ilxomjon o'g'li", 'Xalqaro fakultet', 'Gistologiya va biologiya'),
    ('30302884270038', 'Madaminov Faxriddin Axmadovich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('32806686890011', 'Anvarov Alijon Uktamovich', 'Xalqaro fakultet', "O'zbek va xorijiy tillar"),
    ('42608797040027', 'Nuraliyeva Muborak Tuxtasinovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('30106527080013', 'Yuldashev Xabibullo Ibragimovich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('40309904180020', "G'aniyeva Maftuna Raqiboyevna", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('42411894210017', 'Qosimova Zuxra Madaminjonovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('32104654310027', 'Soliyev Baxtiyor', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('31108866940011', 'Axmedov Avazbek Aliyevich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('42603827040017', 'Abdullayeva Diloramxon Anvarovna', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('32412944310072', "Muxtorov Raufjon Umidjon o'g'li", 'Xalqaro fakultet', 'Ijtimoiy fanlar'),
    ('32503987070037', "Xusanov Azizbek Raximberdi o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('32305866890011', 'Sampath Karikalan', 'Xalqaro fakultet', 'Gistologiya va biologiya'),
    ('32603654310012', "G'aniyev Marufjon Muxammadjonovich", 'Xalqaro fakultet', "O'zbek va xorijiy tillar"),
    ('40402884310073', 'Axmedova Dildora Ilxomovna', 'Xalqaro fakultet', 'Lotin tili, pedagogika va psixologiya'),
    ('32007617040024', 'Mirzayev Olim Jaloldinovich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('31612627040019', 'Sharapov Ilxamberdi Kamalovich', 'Davolash ishi fakulteti', 'Umumiy jarrohlik'),
    ('42204854310027', 'Matisayeva Nasibaxon Abdujabborovna', '', "Talabalar amaliyoti bo'limi"),
    ('41210977070015', 'Shokirova Sitoraxon Borodjon qizi', '', 'Xalqaro fakultet'),
    ('61106007040010', 'Abdulatipova Shahnozaxon Alisher qizi', 'Xalqaro fakultet', 'Gistologiya va biologiya'),
    ('42707734310040', 'Qurbanova Maxsudaxon Muradovna', '', '3-talabalar turar joyi'),
    ('31611816900040', 'Sodikov Ibroximjon Xaydaraliyevich', 'Davolash ishi fakulteti', 'Travmatologiya va ortopediya'),
    ('33105696890011', 'Kodirjonov Ikromjon Zokirovich', 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('32012853910022', 'Karshiyev Fazliddin Shermamatovich', '', 'Rektorat'),
    ('42408967000059', "Axadjonova O'g'iloy Mo'ydinjon qizi", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Biotibbiyot muhandisligi, biofizika va axborot texnologiyalari'),
    ('42804737040018', 'Babadjanova Xursanoy Melibayevna', 'Pediatriya fakulteti', 'Pediatriya'),
    ('41602764190091', "Mo'minova Oftobxon Karimovna", 'Xalqaro fakultet', 'Lotin tili, pedagogika va psixologiya'),
    ('30908757040012', 'Maraimov Ulugbek Muxammadkadirovich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('42803714290057', "Yuldasheva A'loxon Qosimovna", '', "Jismoniy va yuridik shaxslarning murojaatlari bilan ishlash, nazorat va monitoring bo'limi"),
    ('41611887040024', 'Karimova Zilola Sulaymanovna', '', "Ta'lim jarayonini tashkil etish bo'limi"),
    ('30808844310056', 'Mirzayev Azizbek Sharifovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('42111956890015', 'Layeba Kubra Fathima', 'Xalqaro fakultet', 'Fiziologiya'),
    ('41907866890017', 'Iminaxunova Irodaxon Xuseynovna', 'Xalqaro fakultet', "O'zbek va xorijiy tillar"),
    ('42107966890020', 'Xujamberdiyeva Nilufarxon Murodiljon qizi', '', 'Xalqaro fakultet'),
    ('32612814200036', 'Teshaboyev Azizjon Maxammadaliyevich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Mikrobiologiya, virusologiya va immunologiya'),
    ('42001892120061', 'Meliqosimova Barchinoy Toxirjonovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('42111897000045', "Qo'qonboyeva Saodat Solijonovna", 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('40210716890017', 'Xasanboyeva Nafisaxon Abdullojonovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('33107905060022', 'Umarkulov Muxtorali Islomkulovich', 'Pediatriya fakulteti', 'Pediatriya-2'),
    ('30110884310067', 'Shakirov Abrorbek Obidovich', '', 'Davolash ishi fakulteti'),
    ('41111824330048', 'Matmusayeva Otikaxon Usmanaliyevna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('30204844310041', 'Sultanov Bexzad Sardorovich', 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('40904986940023', 'Xoshimova Azizaxon Saxobiddin qizi', 'Xalqaro fakultet', 'Lotin tili, pedagogika va psixologiya'),
    ('42602554310022', 'Tursunova Paridaxon Turgunbayevna', 'Pediatriya fakulteti', 'Nevrologiya va psixiatriya'),
    ('31705817040017', 'Xaydarov Voxidjon Obitovich', '', 'Pediatriya fakulteti'),
    ('50107006980024', "Rustamov Umidjon Maxsudali o'g'li", 'Xalqaro fakultet', 'Ijtimoiy fanlar'),
    ('30112987010022', "G'ofurov Azizbek Baxodirjon o'g'li", 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('62711017080092', 'Yuldasheva Nozimaxon Akmaljon qizi', '', 'Davolash ishi fakulteti'),
    ('40212720200044', 'Raximova Xusnidaxon Abdukarimovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('52108007060054', "Yursinaliyev Muxammadjon Madaminjon o'g'li", '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('31803924310051', "Abdullayev Sardorbek Solijon o'g'li", 'Pediatriya fakulteti', 'Pediatriya'),
    ('30712924340045', "Abdumajidov Axrorjon Akramjon o'g'li", 'Davolash ishi fakulteti', 'Umumiy jarrohlik'),
    ('42602934190040', 'Dadxayeva Gullola Baxtiyorjon qizi', '', 'Iqtidorli talabalarning ilmiy-tadqiqot faoliyatini tashkil etish sektori'),
    ('42809727040016', 'Maksudova Miyassarxan Turdaliyevna', '', 'Xisobxona'),
    ('31807944300012', "Xusanboyev Baxtiyor Xatamboy o'g'li", 'Davolash ishi fakulteti', 'Umumiy jarrohlik'),
    ('32304864140041', 'Turdimatov Uygunjon Xoshimjonovich', '', '3-talabalar turar joyi'),
    ('41402976890022', 'Raja Lohitha', 'Xalqaro fakultet', 'Gistologiya va biologiya'),
    ('30212967040044', "Dolimov Xayotjon Xakimjon o'g'li", '', "Ma'lumotlar ba'zasi bo'limi (Back office)"),
    ('41807977040045', "Xakimova Madina G'ayratjon qizi", '', 'Xalqaro fakultet'),
    ('33012956890013', 'Latif Abdul', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Mikrobiologiya, virusologiya va immunologiya'),
    ('31408874210017', 'Abdulxakimov Arsen Renatovich', 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('41204607040017', 'Yusupova Gulnara Karimovna', 'Xalqaro fakultet', 'Patologik fiziologiya va patologik anatomiya'),
    ('31501964220032', "Ro`zimatov Tohirjon To'lqinboy o'g'li", '', 'Pediatriya fakulteti'),
    ('32005954310053', "Qosimov Sherzodbek Xursanali o'g'li", 'Davolash ishi fakulteti', 'Umumiy jarrohlik'),
    ('41606844270105', 'Ibragimova Maxbubaxon Yakubjonovna', '', 'Xalqaro fakultet'),
    ('31006957040012', 'Ali Shakir', 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('30610924270031', "Abduvosiyev Abdukarim Abduxamit o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Preventiv tibbiyot asoslari, jamoat salomatligi, jismoniy tarbiya va sport'),
    ('30711907080011', 'Maxmudov Boburbek Erkinovich', 'Davolash ishi fakulteti', 'Travmatologiya va ortopediya'),
    ('62402007010068', 'Mamadaliyeva Zuxraxon Botirjon qizi', '', "Talabalarni turar joy bilan ta'minlash va sportga jalb qilish"),
    ('42005914200016', 'Bozorova Munira Baxtiyorjon qizi', 'Davolash ishi fakulteti', 'Travmatologiya va ortopediya'),
    ('31209634330020', 'Atabekov Oxunjon Pulatovich', '', '3-talabalar turar joyi'),
    ('30409944270095', "Abdusalomov Abdulhay Abdumalik o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('42511734310047', 'Xamrakulova Dilbar Abduxalilovna', '', "Yoshlar bilan ishlash, ma'naviyat va ma'rifat bo'limi"),
    ('31906977040053', "Valiyev Alisherjon Latifjon o'g'li", '', 'Registrator Office'),
    ('32002874330020', 'Yusupov Mansurjon Mamajonovich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', "Ovqatlanish, bolalar va o'smirlar gigiyenasi"),
    ('30611996940028', "Nizomov Oybek Farux o'g'li", 'Xalqaro fakultet', 'Gistologiya va biologiya'),
    ('42803954250011', "Meliqo'ziyeva Gulchexra Abdullajon qizi", 'Xalqaro fakultet', "O'zbek va xorijiy tillar"),
    ('41809664330017', 'Akbarova Munajatxon Yusupjanovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Biotibbiyot muhandisligi, biofizika va axborot texnologiyalari'),
    ('30204804310050', 'Aripov Asliddin Maxmudovich', '', "Ma'lumotlar ba'zasi bo'limi (Back office)"),
    ('52906007060025', "Umaraliyev Shohruhbek Rustamjon o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Preventiv tibbiyot asoslari, jamoat salomatligi, jismoniy tarbiya va sport'),
    ('32807914140065', "Xoshimov Ilxomjon Xasan o'g'li", 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('31010724990183', 'Iriskulov Ulugbek Xasiyatkulovich', '', 'Rektorat'),
    ('32411934150023', "Axmadbekov Behzodbek Olimbek o'g'li", 'Davolash ishi fakulteti', 'Fakultet va gospital jarrohlik'),
    ('42111967000014', 'Abdujabborova Charosxon Sanjarbek qizi', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('31208944310148', "Saloxiddinov Eldor Shuxratjon o'g'li", 'Pediatriya fakulteti', 'Urologiya va onkologiya'),
    ('41209764270019', 'Dexkanova Nigora Namanjanovna', 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('31409844220016', 'Isaqov Saidmalik Solijonovich', '', 'Korrupsiyaga qarshi kurashish "Kompleks-nazorat" tizimini boshqarish bo\'limi'),
    ('31602787040039', "Raxmatov Do'stmatjon Zakirovich", '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('32005934310011', "Saydaliyev Saidaziz Baxtiyor o'g'li", 'Pediatriya fakulteti', 'Nevrologiya va psixiatriya'),
    ('42702932100035', "Turg'unpulatova Manzalatxon Sharobiddin qizi", 'Xalqaro fakultet', 'Ijtimoiy fanlar'),
    ('32810664150015', 'Gafurov Abdukayum Pattoyevich', 'Pediatriya fakulteti', 'Pediatriya'),
    ('41502904310058', 'Kuchkarova Dilnoza Tavakalovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('42006966910076', 'Yigitaliyeva Nozimaxon Farxodjon-qizi', 'Xalqaro fakultet', "O'zbek va xorijiy tillar"),
    ('40502744270021', 'Aminjonova Lola Foziljonovna', '', '2-Talabalar turar joyi'),
    ('32507926940018', "Odilov Xurshidjon Akmaljon o'g'li", 'Davolash ishi fakulteti', 'Umumiy jarrohlik'),
    ('40109987040118', 'Musayeva Sadokatxon Abdulokimovna', '', 'Rektorat'),
    ('33001707060010', "Raximov Toxirjon G'aniyevich", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('32002987010020', "Mukarramov Umidjon Movlonjon o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Mikrobiologiya, virusologiya va immunologiya'),
    ('41502834270042', 'Abduvaliyeva Feruzaxon Tulqindjanovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('43108824310075', 'Sotvoldiyeva Nilufar Pazilovna', '', 'Xisobxona'),
    ('43112934310111', 'Saytburxanova Jumagul Aziz qizi', '', 'Davolash ishi fakulteti'),
    ('31111977040071', 'Mohd Sajid Arshad', 'Xalqaro fakultet', 'Fiziologiya'),
    ('42006944310102', 'Aliyeva Zarnigor Valijon qizi', 'Davolash ishi fakulteti', 'Akusherlik va ginekologiya'),
    ('31307924200029', "Esonov Jaxongir G'ayratjon o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('40103907070014', 'Nishanova Shoxida Muydinovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('41404911380036', 'Abduraximova Manzuraxon Shokirjon qizi', 'Xalqaro fakultet', "O'zbek va xorijiy tillar"),
    ('30202564340030', 'Mirzayev Baxtiyor Burxonovich', 'Davolash ishi fakulteti', 'Umumiy jarrohlik'),
    ('42511754310041', 'Xafizova Gulnoza Rasulovna', 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('42601847080020', 'Mirzakalanova Feruza Raximovna', '', 'Pediatriya fakulteti'),
    ('40209934330010', 'Axmadaliyeva Maftuna Abdumanon qizi', 'Pediatriya fakulteti', 'Pediatriya-2'),
    ('30405997020014', "Pulatov Sardorbek Baxodirjon-o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', "Ovqatlanish, bolalar va o'smirlar gigiyenasi"),
    ('60807007010023', 'Isomiddinova Nodirabegim Zarifjon qizi', 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('41509794310043', 'Xaydarova Nargiza Sattarovna', '', "Xalqaro hamkorlik bo'limi"),
    ('33005954180015', "Ne'matjonov Bexruzbek Nurmatjon o'g'li", 'Pediatriya fakulteti', 'Urologiya va onkologiya'),
    ('32009634310010', 'Rasulov Foziljon Xasonovich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Mikrobiologiya, virusologiya va immunologiya'),
    ('30506704160013', 'Umirzaqov Odiljon Ergashovich', 'Davolash ishi fakulteti', 'Ichki kasalliklar propedevtikasi'),
    ('42507877040013', 'Fazilova Nodira Akramovna', 'Xalqaro fakultet', "O'zbek va xorijiy tillar"),
    ('41705914180015', 'Usmonova Maftuna Davlatjon qizi', 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('40803884310049', 'Karimova Nozima Baxtiyarovna', '', "O'quv metodik ta'minot bo'limi"),
    ('41609667040025', 'Nazirjonova Muxabatxon Zikriloevna', '', '1-talabalar turar joyi'),
    ('41309774310047', 'Abduganiyeva Arofat Yermaxamatovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('40612894310031', "Sabirova Xusnigul G'ayratovna", 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('30410934310042', "Maxmudov Maxammaddiyor Soxib o'g'li", '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('41709714310018', 'Saidova Yokut Erkinovna', '', '1-talabalar turar joyi'),
    ('31509997010051', "Abselyamov Dilmurod Rustem o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Preventiv tibbiyot asoslari, jamoat salomatligi, jismoniy tarbiya va sport'),
    ('31501764330014', 'Djanbekov Tursunali Nazimovich', '', '3-talabalar turar joyi'),
    ('31008924280102', "Sobirjonov Sohibjon Aminjon o'g'li", 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('40201894310099', 'Irmatova Nilufar Sadirdinovna', '', 'Davolash ishi fakulteti'),
    ('42112916940016', "Qaxorova Tursinoy Ulug'bek qizi", 'Xalqaro fakultet', "O'zbek va xorijiy tillar"),
    ('31410944270036', "Shuhratjonov Muxammadali Shuhratjon o'g'li", 'Pediatriya fakulteti', 'Pediatriya-2'),
    ('40205914270066', "Boboxonova Muxayyoxon Mo'minjonovna", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('42805934140022', 'Tulanova Moxichexra Akram qizi', 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('31602914190053', "Oxunov Jasurbek Jamoldin o'g'li", 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('40712965540014', 'Ismoiljanova Nilufar Kosimjon qizi', '', 'Xalqaro fakultet'),
    ('31501924180097', "Oripov Nodirbek Mansurjon o'g'li", '', "Xizmat ko'rsatish bo'limi (Front office)"),
    ('40603794310050', 'Kadirova Dilobar Anvarovna', '', 'Xalqaro fakultet'),
    ('31603966890016', "Dilbarjonov Avazbek Ravshanbek o'g'li", 'Xalqaro fakultet', 'Lotin tili, pedagogika va psixologiya'),
    ('31301977040021', "Nabiyev Shoxruxbek Oribjon o'g'li", 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('32005484310042', 'Raxmatullayev Izatulla', 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('42107664310013', 'Tuychiyeva Odina Sobirovna', 'Xalqaro fakultet', 'Lotin tili, pedagogika va psixologiya'),
    ('31405967040010', "Mamaruziyev Murodiljon Erkinjon o'g'li", '', 'Davolash ishi fakulteti'),
    ('40203964310019', 'Ismoilova Husnidaxon Valijon qizi', 'Xalqaro fakultet', "O'zbek va xorijiy tillar"),
    ('30910864310047', 'Shakirov Sardor Abdusaminovich', '', 'Potologik fizologiya potologik anatomiya'),
    ('52512016980016', "Xolmatov Sardor Iqboljon o'g'li", 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('42510824300027', 'Qosimova Gulnoza Soyibjonovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Biotibbiyot muhandisligi, biofizika va axborot texnologiyalari'),
    ('32207996890049', "To'lqinov Islomjon Ikromjon o'g'li", 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('42508924140038', 'Latifjonova Gulnoza Erkinjon qizi', 'Pediatriya fakulteti', 'Urologiya va onkologiya'),
    ('31109916980025', "Usmonov Sanjar Baxromjon o'g'li", 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('40608844270045', 'Xaydarova Azizaxon Tursunboyevna', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('40309977040012', 'Shodmonova Mukarramxon Jaxongir qizi', 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('40702727040018', "Xolmatova Yoqutxon Ne'mattillayevna", 'Davolash ishi fakulteti', 'Umumiy jarrohlik'),
    ('41311924270079', 'Dadajonova Mashxura Axmadjon qizi', 'Davolash ishi fakulteti', 'Fakultet va gospital jarrohlik'),
    ('33010944340076', "Abdurashidov Axrorjon Axmatjon o'g'li", 'Pediatriya fakulteti', 'Urologiya va onkologiya'),
    ('40608891240040', 'Muradimova Alfiya Rashidovna', '', "Ilmiy tadqiqotlar, innovatsiyalar va ilmiy pedagogik kadrlar tayyorlash bo'limi"),
    ('31810706620011', 'Kovrijnix Andrey Anatolevich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('30310706890021', 'Imomov Farxodjon Toshkuziyevich', '', "Talabalar amaliyoti bo'limi"),
    ('41401687040023', 'Saliyeva Nigora Sadikovna', 'Xalqaro fakultet', 'Lotin tili, pedagogika va psixologiya'),
    ('40103977040067', 'Topvoldiyeva Mohitabon Ravshanjon qizi', 'Davolash ishi fakulteti', 'Akusherlik va ginekologiya'),
    ('32703564310019', 'Yuldashov Fayzulla', '', 'Rektorat'),
    ('31908614310071', 'Yuldashev Olimjon Sotvoldiyevich', 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('42601883990053', 'Xoliqova Lutfiya Umurzoqovna', 'Xalqaro fakultet', 'Lotin tili, pedagogika va psixologiya'),
    ('63110007040022', 'Ismonaliyeva Diyora Erkinjonovna', 'Xalqaro fakultet', 'Gistologiya va biologiya'),
    ('32212886900027', 'Mullajonov Xasanboy Ergashaliyevich', 'Pediatriya fakulteti', 'Pediatriya-2'),
    ('40404727040011', 'Djalalidinova Shaxlo Djamalidinovna', 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('32108597080014', 'Saydaliyev Sultangazi Satvaldiyevich', 'Davolash ishi fakulteti', 'Umumiy jarrohlik'),
    ('41908907010018', "Jo'raboyeva Gulxayyo Baxtiyor qizi", 'Davolash ishi fakulteti', "Terapiya yo'nalishidagi fanlar (UASH)"),
    ('32909947040016', "Umurzakov Jamshidbek Jamolitdin o'g'li", 'Pediatriya fakulteti', 'Urologiya va onkologiya'),
    ('30711834210084', 'Yulchiyev Muxiddinjon Qodirovich', '', "Fuqaro va mehnat muxofazasi bo'limi"),
    ('32011614160029', 'Isaqov Axmadqul Mamasidiqovich', '', "Talabalar amaliyoti bo'limi"),
    ('32409996940012', "Odilov Jamshidbek Akmaljon o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Biotibbiyot muhandisligi, biofizika va axborot texnologiyalari'),
    ('40211714310075', 'Raxmonova Sharifa Asankulovna', 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('32810706900013', 'Saminov Toxirjon Kosimovich', '', '1-talabalar turar joyi'),
    ('40106954310142', 'Ergasheva Nodiraxon Atxamjon qizi', 'Xalqaro fakultet', 'Patologik fiziologiya va patologik anatomiya'),
    ('40706997040028', 'Umarova Gullolaxon Abdurashid qizi', 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('30106614310029', 'Egamnazarov Azamjon Imamnazarovich', 'Xalqaro fakultet', 'Ijtimoiy fanlar'),
    ('40205785260014', 'Tojiboyeva Sadoqat Rasulovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('41307934190018', 'Odiljonova Nigoraxon Ikromjon qizi', 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('40502754290015', 'Dadabayeva Parizodxon Uygunovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Preventiv tibbiyot asoslari, jamoat salomatligi, jismoniy tarbiya va sport'),
    ('32802576900026', 'Raxmonov Soyib Ashmatovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('31309584220010', 'Xajimuratov Abdukaxxor Abdumutalovich', 'Xalqaro fakultet', 'Ijtimoiy fanlar'),
    ('32209734310044', 'Ganibayev Ikramjon Shakiraliyevich', 'Davolash ishi fakulteti', 'Ichki kasalliklar propedevtikasi'),
    ('42210874270142', 'Qayumova Shaxloxon Nozimovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('40802944310126', 'Davronova Umidaxon Shomurod qizi', '', '1-talabalar turar joyi'),
    ('31303894270055', 'Xolmatov Shoxrux Murodiljonovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('42906997070034', 'Fozilova Zilola Muhammadqobil qizi', 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('33108914330014', "Nishanov Eshonxuja Xamedxuja o'g'li", 'Davolash ishi fakulteti', 'Travmatologiya va ortopediya'),
    ('41204754190041', 'Nishonova Dilnavoz Jonibekovna', 'Xalqaro fakultet', 'Lotin tili, pedagogika va psixologiya'),
    ('30502684340021', 'Ruzibayev Muxammad Nishanbayevich', 'Pediatriya fakulteti', 'Pediatriya-2'),
    ('31510494270075', 'Maxmudov Zakirjan', 'Xalqaro fakultet', 'Gistologiya va biologiya'),
    ('31302924180098', "Abdumannonov Temurbek Davlatjon o'g'li", '', "Xizmat ko'rsatish bo'limi (Front office)"),
    ('32802996970016', "Aminjonov Bahodirjon Muzaffar o'g'li", 'Xalqaro fakultet', 'Fiziologiya'),
    ('42706904310101', 'Turdibayeva Umida Muxtorovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('32502667040036', 'Djurayev Madamin Davranovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('42607784130053', 'Boretskaya Alisa Sergeyevna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Mikrobiologiya, virusologiya va immunologiya'),
    ('31112976940056', "Obidov Voxidjon Valijon o'g'li", 'Pediatriya fakulteti', 'Dermatovenerologiya va allergologiya'),
    ('63103017010020', 'Ahmadaliyeva Guloyimxon Umidjon qizi', 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('31512757010019', "Boltaboyev Ulug'bek Abdusalimovich", '', 'Rektorat'),
    ('41101871450011', 'Mominjonova Lobarxan Abitxodjayevna', 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('30101674270089', 'Mirzojonov Azimjon Dadajonovich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('41803884310066', 'Mamurova Nilufar Adxamjonovna', '', "Ta'lim jarayonini tashkil etish bo'limi"),
    ('43012844130048', 'Kuziyeva Dilafruz Abdumuxtarovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('42106797040019', 'Karimova Xilola Nosirovna', '', 'Axborot-resurs markazi'),
    ('41508844270092', "G'ulomova Ra'noxon Islomjonovna", 'Davolash ishi fakulteti', 'Akusherlik va ginekologiya'),
    ('33103774270030', 'Osbayov Muhammadjon Imaraliyevich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('41106794210070', 'Tojiboyeva Maxfuzaxon Sayfulloyevna', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('32104904310126', 'Turgunov Ulugbek Raxmatjonovich', '', 'Pediatriya fakulteti'),
    ('51011017040028', "Toyirov Shoxijaxon Umidjon o'g'li", '', "Ta'lim jarayonini tashkil etish bo'limi"),
    ('32307954160024', "Sotvoldiyev Jasurbek Baxtiyor-o'g'li", '', "Ta'lim sifatini ta'minlash"),
    ('31106704310026', 'Boymirzayev Avazjon Komilovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('42904754310092', 'Atadjanova Dilfuza Sharobidinovna', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('31005764310048', 'Raximov Omatjon Nurmuxammadovich', '', "Yoshlar bilan ishlash, ma'naviyat va ma'rifat bo'limi"),
    ('32311664150037', 'Xamrakulov Tulkin Zakirovich', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('40410744270021', 'Maxmudova Xurmatoy Toshtemirovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Preventiv tibbiyot asoslari, jamoat salomatligi, jismoniy tarbiya va sport'),
    ('41009891370059', 'Mamasoliyeva Nazokatxon Xasanboyevna', 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('30109987060038', "Mirzayev Ibroximjon Anvarjon o'g'li", 'Pediatriya fakulteti', 'Urologiya va onkologiya'),
    ('31610934330010', "Akbarov Abbosjon Abdulaxat o'g'li", '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('33103850600023', "Ergashov Umar Shuhrat o'g'li", 'Pediatriya fakulteti', 'Urologiya va onkologiya'),
    ('41712944310101', 'Raxmonova Shoxsanom Raxim qizi', 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('42208977040021', 'Isaqjonova Moxinur Nodirjon qizi', 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('31806944310054', "Azimov Bobirjon Erkinjon o'g'li", '', 'Xalqaro fakultet'),
    ('62009017010024', 'Meliboyeva Munisabonu Elmurod qizi', 'Xalqaro fakultet', 'Ijtimoiy fanlar'),
    ('31110976940012', "Normaxamadov Shokirjon Xursandjon o'g'li", '', 'Rektorat'),
    ('31408816890013', "Oripov Mardonbek Madamin o'g'li", '', "Reja-moliya bo'limi"),
    ('30305914150027', "Yuldashov Sarvarxon Akmaljon o'g'li", 'Davolash ishi fakulteti', 'Umumiy jarrohlik'),
    ('41502754250065', 'Nazarova Yorqinoy Xalpajonovna', 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('40904604310090', 'Kalandarova Matlyuba Xodjiakbarovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('30904754330024', 'Mamazoirov Xaliljon Xokimjonovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('42809797040022', 'Ismailova Shaxzoda Axmadjonovna', '', 'Axborot-resurs markazi'),
    ('40407924160025', "Maxmudova Moxinur Ne'matilla qizi", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('32606884340022', 'Boltabayev Shuxrat Abdusattorovich', '', 'Pediatriya fakulteti'),
    ('32202944310035', 'Shalankov Konstantin Konstantinovich', '', 'Xalqaro fakultet'),
    ('32404997060046', "Abduraximov Xojiakbar Boqijon o'g'li", 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('32207777010011', 'Toshmatov Nuribllo Payzilatbekovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('32511884270023', 'Xaydarov Nodirjon Sovridinovich', 'Davolash ishi fakulteti', 'Umumiy jarrohlik'),
    ('41212854270071', 'Mirzaxmedova Xursanxon Sultonaliyevna', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('33110896940011', 'Turdiyev Xayotbek Ergashboyevich', '', "Ma'lumotlar ba'zasi bo'limi (Back office)"),
    ('30912957000015', "Ahmadjonov Azamatjon Adhamjon o'g'li", '', 'Xalqaro fakultet'),
    ('40901704290035', 'Xamedova Yulduz Raximovna', '', "Yoshlar bilan ishlash, ma'naviyat va ma'rifat bo'limi"),
    ('30406956960044', "Abdujabborov Shuxratjon Abdumalik o'g'li", 'Pediatriya fakulteti', 'Pediatriya-2'),
    ('41505954140020', 'Uktamova Zulayxo Abduxalil qizi', 'Pediatriya fakulteti', 'Pediatriya'),
    ('60611007000023', 'Raxmatullayeva Guljaxon Ulug`bek qizi', 'Xalqaro fakultet', 'Fiziologiya'),
    ('32803934160030', "Hamraqulov Mirzadavlat Jo'raqo'zi o'g'li", 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('41712934310065', 'Irgasheva Nigoraxon Komilovna', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('50405007010033', "Isomiddinov Asadbek Axmadali o'g'li", 'Xalqaro fakultet', 'Fiziologiya'),
    ('40707617040015', 'Mamatqulova Maxbubaxon Tojaliyevna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Mikrobiologiya, virusologiya va immunologiya'),
    ('62706047040017', "O'ktamova Mubinaxon Umidjon qizi", '', 'Xalqaro fakultet'),
    ('41404804130023', 'Maxamatova Umidaxon Rahmonjonovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('41905864190032', 'Raxmanova Shoiraxon Xokimjonovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('41303647040013', 'Alimova Iroda Anvarovna', 'Pediatriya fakulteti', 'Pediatriya'),
    ('42004654210084', 'Djurayeva Kamila Yegitaliyevna', 'Pediatriya fakulteti', 'Pediatriya'),
    ('31804946970021', "Kamolov Javlonbek Shuxratjon o'g'li", '', "Xizmat ko'rsatish bo'limi (Front office)"),
    ('42703734310031', "Yuldasheva Ra'no Valiyevna", '', "Reja-moliya bo'limi"),
    ('31411894300011', "G'ulomqodirov Muzaffar Maxmit o'g'li", 'Pediatriya fakulteti', 'Nevrologiya va psixiatriya'),
    ('40303924270152', 'Muxammadova Gulbaxor Qobiljon qizi', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('42607810280011', 'Maxmudova Moxidil Axmadovna', 'Davolash ishi fakulteti', "Terapiya yo'nalishidagi fanlar (UASH)"),
    ('30805730210018', 'Xusanbayev Abdimajit Abdugapirovich', '', "Jismoniy va yuridik shaxslarning murojaatlari bilan ishlash, nazorat va monitoring bo'limi"),
    ('41506975090017', "Muxtorova Orzuxon Mo'minjon qizi", 'Xalqaro fakultet', "O'zbek va xorijiy tillar"),
    ('30803997080045', "Tursunov Muxammad-amin Fatxulla o'g'li", 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('42209664270035', 'Axmedova Uktamxon', 'Xalqaro fakultet', "O'zbek va xorijiy tillar"),
    ('32112966930055', "Maxmudov O'ktamjon Muxsinjon o'g'li", 'Xalqaro fakultet', 'Ijtimoiy fanlar'),
    ('42404777040012', 'Uralova Nargiza Omanovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('41808784310015', 'Nazirtashova Roziya Mamadaliyevna', 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('33001986960021', "Inomov Xayitali Ergashali o'g'li", '', "Xizmat ko'rsatish bo'limi (Front office)"),
    ('31605807040033', 'Nishonov Shuxratjon Abdullayevich', '', "Talabalarni turar joy bilan ta'minlash va sportga jalb qilish"),
    ('30906996890023', "Abdusattorov Javohirbek Umidjon o'g'li", 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('32604957040022', "Kamolitdinov Xafizitdin Sadritdin o'g'li", 'Davolash ishi fakulteti', 'Fakultet va gospital jarrohlik'),
    ('32611634310026', 'Saliyev Ulugbek Abdullayevich', 'Xalqaro fakultet', 'Ijtimoiy fanlar'),
    ('31801614140078', 'Mamadaliyev Nemat Koxorovich', 'Xalqaro fakultet', 'Ijtimoiy fanlar'),
    ('41008817040030', 'Karimova Anorxon Zoylobidinovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', "Ovqatlanish, bolalar va o'smirlar gigiyenasi"),
    ('40707947060013', 'Mirzajonova Yoqutxon Nosirjon qizi', 'Davolash ishi fakulteti', 'Akusherlik va ginekologiya'),
    ('41405574310037', 'Marupova Manzura Aminovna', 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('30105864310016', 'Turabekov Farxod Kasimovich', '', 'Davolash ishi fakulteti'),
    ('31810894270072', 'Baxromov Avazbek Xoliqovich', '', "Tarmoqlarni boshqarish bo'limi"),
    ('42401824130014', 'Artikova Mavludaxon Raxmanovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('40103914310013', 'Ten Albina Nikolayevna', '', "Yoshlar bilan ishlash, ma'naviyat va ma'rifat bo'limi"),
    ('42002754310073', 'Yuldasheva Moxigul Turdialiyevna', 'Xalqaro fakultet', 'Gistologiya va biologiya'),
    ('41405874130049', "Sheraliyeva Ma'mura Ulugbekovna", '', 'Xalqaro fakultet'),
    ('41311844140025', 'Masharipova Salimaxon Ortikaliyevna', 'Davolash ishi fakulteti', 'Akusherlik va ginekologiya'),
    ('32311864270041', 'Maxamatov Umidjon Shoirjonovich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', "Ovqatlanish, bolalar va o'smirlar gigiyenasi"),
    ('30608894340081', 'Komilov Nodirbek Bokijonovich', '', "O'quv metodik ta'minot bo'limi"),
    ('42312914310060', "Sirajidinova Mua'tarxon Sirajidin qizi", '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('40505894310018', 'Sharipova Madinaxon Arabbayevna', '', 'Davolash ishi fakulteti'),
    ('41407934310015', 'Xoshimova Qutbiniso Boxodir qizi', '', "Yoshlar bilan ishlash, ma'naviyat va ma'rifat bo'limi"),
    ('40808854330131', 'Marupova Nigoraxon Sadikjanovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('40310976940056', 'Mamatxonova Moxichexraxon Ubaydullo qizi', 'Xalqaro fakultet', "O'zbek va xorijiy tillar"),
    ('31602634330016', 'Boltabayev Murodiljon Umarovich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('30810934220028', "Sattorov Sirojiddin Adhamjon o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('30304844310011', 'Nishanbayev Sanjar Odilovich', '', "Talabalarni turar joy bilan ta'minlash va sportga jalb qilish"),
    ('61803017070023', 'Asrorova Maftunabegim Mahammadrizo qizi', 'Pediatriya fakulteti', 'Pediatriya-2'),
    ('31203914310027', 'Ibragimov Saidbek Alisherovich', '', 'Davolash ishi fakulteti'),
    ('42311844330030', 'Kadirova Munira Rasulovna', 'Xalqaro fakultet', 'Lotin tili, pedagogika va psixologiya'),
    ('41606934310115', 'Sabirova Durdonaxon Baxtiyor qizi', '', 'Rektorat'),
    ('40310644310028', 'Axmadulina Galiya Marsovna', 'Davolash ishi fakulteti', "Terapiya yo'nalishidagi fanlar (UASH)"),
    ('41311877040048', 'Ergasheva Surayyo Islyamovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('31605894330019', 'Yusupjonov Murodjon Tolibjonovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('30202804310030', 'Shamshiyev Xojiakbar Xatamovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('32601754310101', "Astanakulov Dilmurod Yo'ldoshovich", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Preventiv tibbiyot asoslari, jamoat salomatligi, jismoniy tarbiya va sport'),
    ('40304844270019', 'Yuldasheva Dilraboxon Ilxomjonovna', '', "Xodimlar bo'limi"),
    ('41211814130019', 'Pulatova Manzuraxon Djurayevna', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('41301977000075', 'Axmadjonova Gulhaiyo Rafiqjon qizi', 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('32105534270026', "Ro'zmatzoda Qodirqul Ruzmat o'g'li", 'Xalqaro fakultet', 'Ijtimoiy fanlar'),
    ('41003864130011', 'Dexkanova Nasiba Xabibullayevna', '', 'Axborot-resurs markazi'),
    ('61204007040022', 'Komiljonova Umida Mamaruzi qizi', 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('31309634170034', 'Ruzaliyev Komiljon Nosirovich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Mikrobiologiya, virusologiya va immunologiya'),
    ('30909957060028', "Marupov Abrorjon Toshturg'un o'g'li", 'Pediatriya fakulteti', 'Nevrologiya va psixiatriya'),
    ('30111887040029', 'Khan Muhammad Amir', 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('32509966890047', "Ismoilov Ulug'bek Ilxomjon o'g'li", 'Davolash ishi fakulteti', "Terapiya yo'nalishidagi fanlar (UASH)"),
    ('41906844310044', 'Sheraliyeva Shirinxon Topvoldiyevna', '', 'Pediatriya fakulteti'),
    ('42202904310096', 'Sadikova Maftuna Azizovna', '', "O'quv metodik ta'minot bo'limi"),
    ('30401964310025', "Abdullayev Sardor Anvar o'g'li", 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('62803027040015', 'Abdullayeva Sarvinozxon Akmaljon qizi', '', "O'qitishning texnik vositalari bo'limi"),
    ('40511914310126', 'Mamataliyeva Janona Alimjanovna', 'Pediatriya fakulteti', 'Nevrologiya va psixiatriya'),
    ('43112902190048', 'Ismatullayeva Roxilaxon Avazxon qizi', '', 'Davolash ishi fakulteti'),
    ('32703997040028', "Asqarov Lazizbek Azizjon o'g'li", '', 'Xalqaro fakultet'),
    ('42506977060046', 'Qodirova Dilfuzaxon Abduraxim qizi', 'Pediatriya fakulteti', 'Dermatovenerologiya va allergologiya'),
    ('40202757040014', 'Shakirova Zuxra Xamidovna', '', 'Xisobxona'),
    ('32111934310055', "Jo'rayev Javohir Jaxongir o'g'li", '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('31612946960016', "Akramov G'ayratjon Soyibjon o'g'li", 'Pediatriya fakulteti', 'Nevrologiya va psixiatriya'),
    ('41912884220098', 'Shodiyeva Elmira Yusupjonovna', 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('40202674310058', 'Xolnazarova Shoiraxon Numanovna', '', 'Malaka oshirish va qayta tayyorlash fakulteti'),
    ('32509975970024', "Sobitjonov Umidjon Haydarali o'g'li", '', 'Xalqaro fakultet'),
    ('42612893980060', 'Bekkulova Mohigul Abdurasulovna', 'Davolash ishi fakulteti', 'Ichki kasalliklar propedevtikasi'),
    ('31302914160042', "Yigitaliyev Alisher Baxodir o'g'li", 'Pediatriya fakulteti', 'Urologiya va onkologiya'),
    ('40402884270029', 'Usupova Nasiba Nabijonovna', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('32707977010063', "Rahmatshoyev Muslimbek Nozimjon o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('31604904310010', 'Yusupov Abdulaziz Adxamjonovich', '', 'Davolash ishi fakulteti'),
    ('42712844290021', 'Kadirova Xulkaroy Abduvasiyevna', 'Xalqaro fakultet', 'Gistologiya va biologiya'),
    ('41009767040013', 'Kurbonova Aziza Anvarovna', '', 'Xalqaro fakultet'),
    ('33010997040077', "Axmadjonov Qudratjon Adxam o'g'li", '', "Tarmoqlarni boshqarish bo'limi"),
    ('41506864330024', 'Yuldashova Xilola Maxkamovna', '', "Yoshlar bilan ishlash, ma'naviyat va ma'rifat bo'limi"),
    ('41108997040069', 'Abdunazarova Madinabonu Arabboy qizi', 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('42201754270028', 'Mirqurbanova Taxmina Xamidzoda', 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('40901734270049', 'Shakirova Nigora Ismailovna', '', 'Devonxona va arxiv'),
    ('32607944250024', "Abduraxmonov Niyozbek Xamdamjon o'g'li", 'Davolash ishi fakulteti', 'Umumiy jarrohlik'),
    ('30312916980044', "Axadjonov Mavlonjon Maxmudjon o'g'li", 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('31004687040014', "Xaydarov G'ayrat Melikuziyevich", 'Davolash ishi fakulteti', 'Fakultet va gospital jarrohlik'),
    ('40105717040014', 'Azimova Mayram Kurbanovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('33005986910035', "Baxodirov Javohir Axadjon-o'g'li", '', "O'qitishning texnik vositalari bo'limi"),
    ('31810914310090', "Teshabayev Azamatjon Adxamjon o'g'li", '', 'Davolash ishi fakulteti'),
    ('43001776890012', "Melibayeva Farog'at Madaminovna", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Biotibbiyot muhandisligi, biofizika va axborot texnologiyalari'),
    ('32107976960020', "Qurbonov Pahlavon Sirojiddin o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Biotibbiyot muhandisligi, biofizika va axborot texnologiyalari'),
    ('40610594310056', 'Zakiryayeva Elmira Xolmatovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('31510726890013', 'Djurabayev Avaz Azizovich', 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('30802944310066', "Qo'ziboyev Shohruhbek Ibrohim o'g'li", 'Davolash ishi fakulteti', 'Fakultet va gospital jarrohlik'),
    ('52101027040015', "Tursunaliyev Odiljon Olimjon o'g'li", '', 'Xalqaro fakultet'),
    ('30405734310024', 'Qosimov Kozimjon Isoqovich', 'Xalqaro fakultet', 'Ijtimoiy fanlar'),
    ('40303934310033', "G'ofurova Charosxon Ilxom qizi", '', 'Davolash ishi fakulteti'),
    ('72074141360122', 'Musthaq Ahmed Mohamed', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Mikrobiologiya, virusologiya va immunologiya'),
    ('30209944270048', "Usmonov Saidjon Abdusubxon o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Biotibbiyot muhandisligi, biofizika va axborot texnologiyalari'),
    ('41005964310078', 'Egamkulova Xurshidaxon Tavakaljon qizi', '', '2-Talabalar turar joyi'),
    ('31009854340038', 'Axunbayev Otabek Adilovich', 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('40603977040031', 'Imomnazarova Dilyora Faxriddin qizi', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Preventiv tibbiyot asoslari, jamoat salomatligi, jismoniy tarbiya va sport'),
    ('32407785050012', 'Abduazizov Elyorjon Qoyiljonovich', '', 'Xalqaro fakultet'),
    ('41307966890029', 'Abdurashidova Oydinxon Gafurjon qizi', '', 'Axborot-resurs markazi'),
    ('31501964190023', "Ismoilov Dilmurod Tavakkal o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('40906864140075', 'Mirzajonova Zulayxoxon Melijonovna', 'Davolash ishi fakulteti', 'Akusherlik va ginekologiya'),
    ('42310844210018', 'Umarova Musharraf Yunusaliyevna', 'Xalqaro fakultet', 'Ijtimoiy fanlar'),
    ('40810967040010', 'Abdullayeva Dilnavoz Ismonjon qizi', '', 'Pediatriya fakulteti'),
    ('31505987060095', "Marufzoda Islomjon Omonjon o'g'li", '', "Klinik o'quv bazalar bilan ishlash bo'limi"),
    ('42003917010014', 'Isaqova Nasiba Raxmatjonovna', 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('43008944210016', 'Azimova Karomatposhsho Axmadzoda', 'Davolash ishi fakulteti', 'Akusherlik va ginekologiya'),
    ('30107894310099', 'Ganiyev Sardor Saminjonovich', 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('31208734310048', 'Eshonov Ravshanbek Muxammadmusayevich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Biotibbiyot muhandisligi, biofizika va axborot texnologiyalari'),
    ('31909944310054', "Jabborov Azizxon Akmaljon o'g'li", 'Pediatriya fakulteti', 'Nevrologiya va psixiatriya'),
    ('42804607040023', 'Akbarova Gulchexra Xabibullayevna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('43004987030020', 'Anvarjonova Layloxon Azizjon qizi', 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('32108924190018', "To'ychiyev Rashidbek Valijon o'g'li", 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('30610954190011', "Xatamov Rustamjon Islomjon o'g'li", 'Xalqaro fakultet', 'Patologik fiziologiya va patologik anatomiya'),
    ('41403764310036', 'Akramova Dilfuza Maxmudovna', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('52406017070024', "O'ktamov Paxlavonjon Odiljon o'g'li", '', 'Xalqaro fakultet'),
    ('42012724310017', 'Eminova Xursandoy Abduraximovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('31801924150037', "Badriddinov Oyatillo Usmonjon o'g'li", 'Xalqaro fakultet', 'Patologik fiziologiya va patologik anatomiya'),
    ('41301774310074', 'Musayeva Ziyodaxon Axmadjonovna', '', 'Davolash ishi fakulteti'),
    ('30711724310049', 'Yusupov Abdumalik Raxmonberdiyevich', 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('41406870210023', 'Xamdamova Shaxnozaxon Yusupaliyevna', 'Xalqaro fakultet', "O'zbek va xorijiy tillar"),
    ('42602844130013', 'Marupova Nargiza Anvarovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('31301821290024', 'Azizov Xurshidbek Anvarbekovich', '', 'Davolash ishi fakulteti'),
    ('31406707040033', 'Yunusov Poziljon Maxamatovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('31706957030029', "Davlatov Shohjaxonbek Qurbonbek o'g'li", 'Davolash ishi fakulteti', "Terapiya yo'nalishidagi fanlar (UASH)"),
    ('32204917080011', "Axmadjon Abduma'ruf Isoq o'g'li", 'Pediatriya fakulteti', 'Nevrologiya va psixiatriya'),
    ('32909956970065', "Muhammadiyev Sobirjon Uchqunjon o'g'li", 'Davolash ishi fakulteti', 'Travmatologiya va ortopediya'),
    ('32605924140110', "Pirmatov Shaxbozbek Shuxratbek o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('31809754270011', "Abdullayev O'tkirjon Mashrabovich", 'Xalqaro fakultet', 'Patologik fiziologiya va patologik anatomiya'),
    ('40108914170049', 'Raximova Lolaxon Abduraximovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Biotibbiyot muhandisligi, biofizika va axborot texnologiyalari'),
    ('43001884220026', 'Ikramova Nodira Maxmudovna', 'Xalqaro fakultet', 'Fiziologiya'),
    ('30602977040031', "Ahmedov Ahadulla Qosim o'g'li", 'Davolash ishi fakulteti', 'Ichki kasalliklar propedevtikasi'),
    ('32102944270028', "Meliboyev Ro'zalijon Abdusattor o'g'li", 'Davolash ishi fakulteti', 'Fakultet va gospital jarrohlik'),
    ('40209684310018', 'Tilyaxodjayeva Gulbaxor Batirovna', 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('40501747070018', 'Quziboyeva Arofatxon Yunusaliyevna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('40703904270013', 'Irgasheva Maxbubaxon Davlatjon qizi', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('32006870190044', 'Sidikov Akmal Abdikaxarovich', '', 'Rektorat'),
    ('5106679042422', 'Noor Alam', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('31505964270015', "G'ofurjonov Mirzohid Mirzaxpar o'g'li", 'Pediatriya fakulteti', 'Pediatriya-2'),
    ('31201904330059', 'Xojiraxmatov Davron Kamolidinovich', 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('31104826600010', 'Avazxanov Jaloliddin Payzilidinovich', 'Pediatriya fakulteti', 'Urologiya va onkologiya'),
    ('41310917040037', 'Gasanova Nigora Muxtorovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Biotibbiyot muhandisligi, biofizika va axborot texnologiyalari'),
    ('33004944270033', "Qoraboyev Jasurbek Mavlonjon o'g'li", 'Davolash ishi fakulteti', 'Travmatologiya va ortopediya'),
    ('31410914310058', "Muxammadsidiqov Muxammadbobur Rasuljon o'g'li", '', "Raqamli ta'lim texnologiyalari markazi"),
    ('40610904310064', 'Yusupova Nilufar Baxtiyorovna', '', 'Xalqaro fakultet'),
    ('31801654290010', 'Abdukarimov Nadir Mamurovich', 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('30610514340016', 'Maxmudov Nurillo Ismailovich', 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('41704784270114', 'Raximberdiyeva Feruza Egamberdiyevna', '', "Xodimlar bo'limi"),
    ('41705697040032', 'Abduraximova Naziraxon Eshanjonovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('32906756900034', 'Jabborov Xayrullo Baxromovich', '', 'Rektorat'),
    ('42907864130022', 'Axmatjanova Mukaddam Aminovna', '', "Ilmiy tadqiqotlar, innovatsiyalar va ilmiy pedagogik kadrlar tayyorlash bo'limi"),
    ('30409894190078', 'Aliyev Nurillo Abdiqayumovich', '', "Ma'lumotlar ba'zasi bo'limi (Back office)"),
    ('30803977040074', "Abdumo'minov Boburbek Rustamjon o'g'li", 'Xalqaro fakultet', 'Patologik fiziologiya va patologik anatomiya'),
    ('40509807040038', 'Kozuboyeva Sevaraxon Abdusoliyevna', '', 'Xisobxona'),
    ('31305987040051', "Mamaraimov Ashuroxun Abdumutalib o'g'li", 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('31509966940064', "Toxirov Farmon G'anisher o'g'li", 'Pediatriya fakulteti', 'Pediatriya-2'),
    ('42005997020044', 'Oribjonova Vasilaxon Fizuliddin-qizi', 'Pediatriya fakulteti', 'Pediatriya'),
    ('40710871470050', 'Mirzajonova Saboxon Abjalilovna', 'Xalqaro fakultet', 'Fiziologiya'),
    ('33107976940036', "Yoqubov Doniyorbek Yoqubjon o'g'li", 'Davolash ishi fakulteti', 'Fakultet va gospital jarrohlik'),
    ('30108944310050', "Mo`minov Jahongir Zokirjon o'g'li", 'Davolash ishi fakulteti', "Terapiya yo'nalishidagi fanlar (UASH)"),
    ('30703754310070', 'Xodjamberdiyev Akram Ilxamjanovich', 'Xalqaro fakultet', 'Fiziologiya'),
    ('30808967040034', 'Khan Niyamat', 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('32101824130014', 'Xabibulloyev Dilshod Xabibullo ugli', '', 'Davolash ishi fakulteti'),
    ('32305814330051', "Yusupov G'ulomjon Yakubjonovich", '', '3-talabalar turar joyi'),
    ('40702636890014', 'Akbarova Ranaxon Komiljonovna', 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('31609754150021', 'Axmadaliyev Rustamjon Umaraliyevich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Preventiv tibbiyot asoslari, jamoat salomatligi, jismoniy tarbiya va sport'),
    ('41811817040027', 'Madraximova Gulnora Anvarovna', '', 'Pediatriya fakulteti'),
    ('31004936970019', "Mirzaqandov Elyor Erkinjon o'g'li", 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('42504987080034', "Asqarova Feruza G'ayratjon qizi", 'Pediatriya fakulteti', 'Pediatriya'),
    ('42204944310052', 'Shalankova Olga Yevgenevna', 'Davolash ishi fakulteti', 'Akusherlik va ginekologiya'),
    ('32905954270015', "Tojiboyev Lazizjon Topvoldi o'g'li", '', 'Pediatriya fakulteti'),
    ('41105862120053', 'Umarova Malika Pulatjonovna', 'Pediatriya fakulteti', 'Nevrologiya va psixiatriya'),
    ('31702640201518', "Tuxtamatov Ravshan Xalmat o'g'li", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('41809734160030', 'Xaydarova Buzulayxo Axmedovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('41306804210018', "G'ulomova Muqaddasxon Zaylobidinovna", '', '1-talabalar turar joyi'),
    ('30203967080062', "Raxmonov Baxrombek Baxtiyor o'g'li", 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('31011934111052', "Jaloliddinov Sherzodbek Ikromjon o'g'li", 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('94102352703143', 'Khan Salman Ahmad', 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('31604954140045', "Jo'rayev Muxammadkarim Mirzamumin o'g'li", 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('43011777040033', 'Nishanova Mamuraxon Numonjonovna', '', "Axborot-kutubxona resurslari bilan xizmat ko'rsatish bo'limi"),
    ('31108884340013', 'Xashimov Azizxon Alisherovich', 'Davolash ishi fakulteti', "Terapiya yo'nalishidagi fanlar (UASH)"),
    ('40311767040016', 'Mamatxanova Gulnora Maxmudovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Preventiv tibbiyot asoslari, jamoat salomatligi, jismoniy tarbiya va sport'),
    ('61908006940027', 'Aliyeva Durdonaxon Shuxratjon qizi', 'Pediatriya fakulteti', 'Pediatriya'),
    ('31106947060034', "Jo'rayev Sardorbek Baxodir o'g'li", 'Davolash ishi fakulteti', 'Fakultet va gospital jarrohlik'),
    ('51109005900017', "Mirkalamov Mirjaxon Mirpo'lat o'g'li", 'Xalqaro fakultet', 'Gistologiya va biologiya'),
    ('30704925090018', "Latibjonov Azizbek Erkinjon o'g'li", 'Davolash ishi fakulteti', 'Travmatologiya va ortopediya'),
    ('40505934300058', "Saminova Shodyonaxon A'zamjon qizi", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Preventiv tibbiyot asoslari, jamoat salomatligi, jismoniy tarbiya va sport'),
    ('33010934270024', "Raximov Alisherjon Akmaljon o'g'li", 'Pediatriya fakulteti', 'Nevrologiya va psixiatriya'),
    ('42812934510023', 'Akramzoda Muxayyo Mirzaraxim qizi', '', 'Xalqaro fakultet'),
    ('31604624310028', 'Ismailov Baxromiddin Zaxriddinovich', 'Pediatriya fakulteti', 'Pediatriya'),
    ('42701897040011', 'Uraimova Gulmira Erkinovna', '', 'Pediatriya fakulteti'),
    ('41706704270013', 'Raxmatova Feruza Uraimovna', 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('43005836890017', "Saidumarova Marg'uba Tulanovna", 'Xalqaro fakultet', 'Patologik fiziologiya va patologik anatomiya'),
    ('42509717040030', 'Saitburxanova Saodatxon Rayimjonovna', '', '3-talabalar turar joyi'),
    ('33107664310033', 'Muratov Taxir Musayevich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('30409537080012', 'Tuychibekov Shukurbek', 'Davolash ishi fakulteti', 'Fakultet va gospital jarrohlik'),
    ('31403854200011', 'Akbarov Farrux Saydaliyevich', 'Malaka oshirish va qayta tayyorlash fakulteti', 'Vrachlar malakasini oshirish va qayta tayyorlash kafedrasi'),
    ('33005494310042', 'Xoliddinov Xosiljon', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Biotibbiyot muhandisligi, biofizika va axborot texnologiyalari'),
    ('42507854310029', 'Mamadaliyeva Adibaxon Ravshanovna', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('41310834330020', 'Azimova Gulnoza Ravshanovna', 'Davolash ishi fakulteti', 'Umumiy jarrohlik'),
    ('33001967030037', "Abdumo'minov Ulug'bek Oribjon o'g'li", 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('32908807040045', 'Ibragimov Oybek Alimovich', '', 'Xisobxona'),
    ('33006944240014', "G'anijonov Polvonjon Hasanjonovich", 'Xalqaro fakultet', 'Fiziologiya'),
    ('31409914310010', "Ismailov Diyorbek Adxamjon o'g'li", 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('40409864310032', 'Mamajonova Maftuna Adxamovna', '', "1-bo'lim"),
    ('30710884310094', 'Kadirov Anvar Ibragimovich', '', "Ma'lumotlar ba'zasi bo'limi (Back office)"),
    ('41303794330016', 'Mashrapova Safinaxon Ruziboyevna', '', '3-talabalar turar joyi'),
    ('31312884320041', 'Maxmutov Rustam Xamitovich', 'Pediatriya fakulteti', 'Nevrologiya va psixiatriya'),
    ('40504744310040', 'Teshaboyeva Faridaxon Alibekovna', '', "Xodimlar bo'limi"),
    ('31405934330061', "Kenjayev Sherzod Ravshan o'g'li", 'Davolash ishi fakulteti', 'Travmatologiya va ortopediya'),
    ('30508924270020', "Bobojonov Sardorbek Solijon o'g'li", 'Davolash ishi fakulteti', "Terapiya yo'nalishidagi fanlar (UASH)"),
    ('31712834190030', 'Iskandarov Doniyor Boxodirovich', 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('40509804310048', 'Babaxodjayeva Oydinxon Alisherovna', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('41212834220072', 'Xaliqova Fotimaxon Qodiraliyevna', '', "Xodimlar bo'limi"),
    ('32803757040012', 'Axmedov Pulat Xamidovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('41110857040018', 'Raximjonova Odinaxon Raxmonovna', '', 'Xisobxona'),
    ('42303587040013', 'Palvanova Matlyubaxon Satvaldiyevna', 'Davolash ishi fakulteti', 'Normal anatomiya'),
    ('32503634150020', 'Kazakov Baxodir Soliyevich', '', 'Korrupsiyaga qarshi kurashish "Kompleks-nazorat" tizimini boshqarish bo\'limi'),
    ('30805731240029', 'Toshmatov Farxodjon Rustamovich', 'Davolash ishi fakulteti', 'Travmatologiya va ortopediya'),
    ('32709894210010', 'Muydinov Firuzjon Farxodjonovich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Biotibbiyot muhandisligi, biofizika va axborot texnologiyalari'),
    ('41608954280036', "Sobirjonova Shaxzodaxon G'offorjon-qizi", 'Pediatriya fakulteti', 'Dermatovenerologiya va allergologiya'),
    ('61906017040022', 'Muxamadova Salimaxon Erkinjon qizi', '', 'Rektorat'),
    ('32601564290017', "Malikov Ne'mat Muxtarovich", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', "Ovqatlanish, bolalar va o'smirlar gigiyenasi"),
    ('32005954340023', "Muxammadsodiqov Muxammadrasul Masrurjon o'g'li", 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('32202954310025', "Suyarov Shoxrux Murodil o'g'li", 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('30508664310017', 'Shermatov Rasuljon Mamasiddiqovich', 'Pediatriya fakulteti', 'Pediatriya'),
    ('32309834310084', 'Matxoshimov Nodirjon Soyibjonovich', '', 'Malaka oshirish va qayta tayyorlash fakulteti'),
    ('40903856890015', "Qadirjanova Feruzaxon Ne'matjonovna", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('41210744310038', 'Axmadaliyeva Gulnora Xamrokulovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Biotibbiyot muhandisligi, biofizika va axborot texnologiyalari'),
    ('32107914310069', "Ismoiljanov Nizomiddin Ilxom o'g'li", '', 'Davolash ishi fakulteti'),
    ('42501777040021', 'Kimsanbayeva Xurmatay Ismailjanovna', '', "Xalqaro hamkorlik bo'limi"),
    ('42604947040015', 'Muxammadsidiq qizi Gulxayo', '', 'Xalqaro fakultet'),
    ('31408817040013', 'Satvaldiyev Ixtiyarjon Umarjanovich', 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('40205717080013', 'Karimova Mukimaxon Muxamadsadikovna', 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('50306027040085', "Mamiraliyev Humoyunbek Qahramonjon o'g'li", '', "Xizmat ko'rsatish bo'limi (Front office)"),
    ('42610707040034', 'Muxidinova Shoiraxon Baxramovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('43001904310032', 'Keldiyeva Umidaxon Raxmatjonovna', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('42603754310041', 'Xamrokulova Gulbaxor Abdullayevna', '', 'Pediatriya fakulteti'),
    ('40904894340027', 'Mamadjanova Risolat Abduvaxabovna', 'Davolash ishi fakulteti', 'Travmatologiya va ortopediya'),
    ('43011776890019', 'Tuychibayeva Oydinoy Jorojanovna', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('41002911240075', 'Bobojonova Nilufar Ismail qizi', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('31908934190065', "Abduvaliyev Begali Sherali o'g'li", 'Pediatriya fakulteti', 'Dermatovenerologiya va allergologiya'),
    ('42801894310091', 'Ubaydullayeva Gulnoza Muxamadovna', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('40708894310134', 'Akramova Dilnozaxon Baxramjon Kizi', '', '1-talabalar turar joyi'),
    ('33011794310033', 'Rayimov Alisher Xoldorovich', '', 'Davolash ishi fakulteti'),
    ('42101717040018', 'Xoliqova Oyistaxon Yuldashevna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Xalq tabobati va farmakologiya'),
    ('30206584310042', 'Fattaxov Nusratullo Xamidullayevich', 'Davolash ishi fakulteti', 'Fakultet va gospital jarrohlik'),
    ('32512946930017', "Qosimov Adxamjon Yoqub o'g'li", '', "Ma'lumotlar ba'zasi bo'limi (Back office)"),
    ('31507976940027', "Zokirjonov Diyorbek Zafarjon o'g'li", 'Xalqaro fakultet', 'Patologik fiziologiya va patologik anatomiya'),
    ('30208794310047', 'Nosirov Nodirbek Valijonovich', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Biotibbiyot muhandisligi, biofizika va axborot texnologiyalari'),
    ('32108936900023', "G'ulomov Qaxxorali Qodirali o'g'li", 'Pediatriya fakulteti', 'Nevrologiya va psixiatriya'),
    ('32001996920027', "Ashuraliyev Xondamir To'lqinjon o'g'li", '', "Raqamli texnologiyalarni joriy etish bo'limi"),
    ('41108764210051', 'Qodirova Diloromxon Abdumansurovna', '', 'Tibbiy profilaktika va jamoat salomatligi fakulteti'),
    ('40506894310035', 'Tashmatova Maftuna Ilxamovna', '', "Ta'lim sifatini ta'minlash"),
    ('40112967040019', 'Sattaraliyeva Hayotxon Botirali qizi', 'Davolash ishi fakulteti', 'Akusherlik va ginekologiya'),
    ('32311946910032', "Jo'rayev Xondamir Alisher o'g'li", 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('41108694310045', 'Ashurova Manzuraxon Djaloldinovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('42908784330051', 'Mamajonova Matlubaxon Xolmatovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('50304006940012', "Tursunaliyev Jamshidbek Qaxramonjon o'g'li", '', "Xizmat ko'rsatish bo'limi (Front office)"),
    ('52412027010048', "Ismoilov Sanjarbek Saloxiddin o'g'li", '', "Raqamli texnologiyalarni joriy etish bo'limi"),
    ('32611934270020', "Oribjonov Otabek Erkinjon o'g'li", 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('42409867040011', 'Nabiyeva Gulnoza Axmadovna', '', 'Davolash ishi fakulteti'),
    ('42105664270032', 'Xalilova Barchinoy Rasulovna', 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('40107977040038', 'Oltinboyeva Zarnigor Avazbek qizi', 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('40811914310073', 'Saydullayeva Kamila Mirshodovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', "Ovqatlanish, bolalar va o'smirlar gigiyenasi"),
    ('42604891230016', 'Shamsutdinova Guzel Baxodirovna', 'Davolash ishi fakulteti', "Terapiya yo'nalishidagi fanlar (UASH)"),
    ('40406954270076', 'Tashmamatova Dilnozaxon Kimsanali qizi', 'Pediatriya fakulteti', 'Pediatriya'),
    ('40611734310028', "Muydinova Yokutxon G'iyazidinovna", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Kommunal va mehnat gigienasi'),
    ('31810744130039', 'Turdiyev Shavkat Mamirovich', '', "Magistratura bo'limi"),
    ('40409854270012', 'Rasulova Moxidil Tursunaliyevna', '', 'Davolash ishi fakulteti'),
    ('40810934310029', 'Oribjonova Hadisaxon Abdumutallib qizi', 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('41911704310023', 'Djurabayeva Inoyatxon Mamirovna', '', "Yoshlar bilan ishlash, ma'naviyat va ma'rifat bo'limi"),
    ('41406934270068', "Qodirova Gulira'no Abduxapiz qizi", 'Tibbiy profilaktika va jamoat salomatligi fakulteti', 'Epidemiyologiya va yuqumli kasalliklar, hamshiralik ishi'),
    ('41405864190075', 'Isroilova Gulsanam Muxtorjon qizi', 'Davolash ishi fakulteti', 'Akusherlik va ginekologiya'),
    ('31710924300013', "O'rmonov Dadaxon G'olibjon o'g'li", 'Xalqaro fakultet', 'Tibbiy va biologik kimyo'),
    ('41003834140017', 'Xolmatova Sanobarxon Odiljonovna', '', 'Davolash ishi fakulteti'),
    ('32506944190089', "Yoqubov Farrux Farxodjon o'g'li", 'Pediatriya fakulteti', 'Dermatovenerologiya va allergologiya'),
    ('30510810222310', 'Xaydarov Azizjon Qosimovich', 'Davolash ishi fakulteti', 'Travmatologiya va ortopediya'),
    ('40110954300012', 'Kamalova Sayyoraxon Saloxiddin qizi', 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('41506864310044', 'Alimova Madina Baxodirovna', '', 'Pediatriya fakulteti'),
    ('41201756940027', 'Ibragimova Ziyodaxon Jalolidinovna', 'Xalqaro fakultet', 'Gistologiya va biologiya'),
    ('40410926900016', "Jo'rayeva Mastura Tojixakim qizi", 'Xalqaro fakultet', 'Lotin tili, pedagogika va psixologiya'),
    ('40704777040026', 'Sharopova Shaxnoza Abduqodirovna', '', '3-talabalar turar joyi'),
    ('31212754270080', 'Urunboyev Avazjon Nozimjonovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('42802754310033', 'Ashurova Mukadas Djaloldinovna', 'Tibbiy profilaktika va jamoat salomatligi fakulteti', "Ovqatlanish, bolalar va o'smirlar gigiyenasi"),
    ('31204654260012', 'Kadirov Shuxrat Abdumanonovich', '', 'Rektorat'),
    ('42404624310064', 'Kattaxanova Rabiya Yuldashevna', 'Davolash ishi fakulteti', 'Ichki kasalliklar propedevtikasi'),
    ('42705837040035', 'Abdunazarova Nigoraxon Yaminjonovna', '', "2-bo'lim"),
    ('32909854250081', "O'rinov Azizbek Raxmonberdiyevich", 'Pediatriya fakulteti', 'Stomatologiya va otoloringologiya'),
    ('40901942140064', 'Jabborova Munisxon Abdubanon qizi', 'Davolash ishi fakulteti', 'Akusherlik va ginekologiya'),
    ('32401934340108', "G'aniyev Muxammadamin Avazbek o'g'li", '', 'Rektorat'),
    ('42010757070010', "Ne'matjonova Nilufar Ro'zimamatovna", '', '2-Talabalar turar joyi'),
    ('31102976890015', 'Deepak Sharma', 'Davolash ishi fakulteti', 'Umumiy jarrohlik'),
    ('31508574140022', 'Saminov Xoshim Kosimovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('40808814290026', 'Gulamova Naziraxon Raxmatjonovna', '', 'Iqtidorli talabalarning ilmiy-tadqiqot faoliyatini tashkil etish sektori'),
    ('41311777040023', 'Davronova Mavjuda Sativoldiyevna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('31609977070012', "Jamoldinov Fazliddin Faxriddin o'g'li", '', "Xizmat ko'rsatish bo'limi (Front office)"),
    ('32407664210018', 'Mamatkulov Baxtiyor Raxmonovich', '', '1-talabalar turar joyi'),
    ('32507976910036', "Abdumannonov Abrorjon Ikromjon o'g'li", 'Pediatriya fakulteti', 'Endokrinologiya, gematologiya va ftiziatriya kafedrasi'),
    ('42510864310022', 'Bozorova Xuriyatxon Karimberdiyevna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('40802874270071', 'Soyibnazarova Dilafruz Bobojonovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('42705966980017', "Tursunaliyeva Hojiraxon G'ulomjon qizi", 'Davolash ishi fakulteti', 'Gospital terapiya (laboratoriya)'),
    ('40105837040019', 'Madaminova Zilola Zakirdjonovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('41411744310019', 'Gisitdinova Ulmas Yakubovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('40209874310013', "Mirzadjanova Ma'mura Saydullajonovna", '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('32604934310045', "Qo'rg'onboyev Nuriddin Alijonovich", '', 'Vivariylar'),
    ('31104864270048', 'Jalolov Umidjon Raxmonaliyevich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('32102754310084', 'Tashtemirov Valisher Karimovich', '', '1-talabalar turar joyi'),
    ('43008727040018', 'Radjapova Dilfuzaxon Musayevna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('31305640080026', 'Sultanov Gulamjon Anvarbekovich', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('41009884330046', 'Davranova Zulxumor Sobirjonovna', '', "Texnik foydalanish va xo'jalik bo'limi"),
    ('32005956930035', "Yo'ldoshev Sobitali Zoxidjon o'g'li", '', "Ta'lim sifatini ta'minlash"),
    ('42903914310079', 'Komilova Mohitabon Ramish qizi', 'Xalqaro fakultet', "O'zbek va xorijiy tillar"),
    ('42710967040022', 'Abdumutalova Muxlisaxon Mirzahatam qizi', 'Davolash ishi fakulteti', "Terapiya yo'nalishidagi fanlar (UASH)"),
    ('41311784310092', 'Shermatova Sayyora Alijonovna', '', 'Devonxona va arxiv'),
    ('30311967000099', "Xalilov Nurilloxon Abdug'ani o'g'li", 'Davolash ishi fakulteti', "Terapiya yo'nalishidagi fanlar (UASH)"),
]


def _fac_key(name: str) -> str:
    """Fakultet nomini solishtirish uchun kalitga aylantiradi.

    "Davolash ishi fakulteti" va "Davolash ishi" — bitta fakultet.
    Tizimda dastlab qisqa nomlar bor edi, kadrlar ro'yxatida esa to'liq
    rasmiy nomlar. Ularni oddiy tenglik bilan solishtirsak, bazada
    "Pediatriya" va "Pediatriya fakulteti" degan ikkita qator paydo
    bo'lardi, admin paneldagi filtrda esa ikkita bir xil tugma —
    va foydalanuvchi qaysi birini bosishni bilmasdi.
    """
    key = name.strip().lower()
    for suffix in (" fakulteti", " fakultet"):
        if key.endswith(suffix):
            key = key[: -len(suffix)]
    return key.strip()


async def _faculty_map(db: AsyncSession) -> dict[str, Faculty]:
    """Mavjud fakultetlar, solishtirish kaliti bo'yicha."""
    result = await db.execute(select(Faculty))
    return {_fac_key(f.name): f for f in result.scalars().all()}


async def _ensure_faculties(db: AsyncSession, names: set[str], dry_run: bool) -> dict[str, Faculty]:
    """Fakultetlarni tayyorlaydi.

    Mos keladigan qator topilsa — u ISHLATILADI va nomi kadrlar
    ro'yxatidagi rasmiy nomga yangilanadi. Yangi qator yaratilmaydi,
    ya'ni unga allaqachon bog'langan talabalar va guruhlar joyida
    qoladi.
    """
    existing = await _faculty_map(db)
    created = 0
    renamed = 0
    reused = 0

    for name in sorted(names):
        if not name:
            continue
        key = _fac_key(name)
        found = existing.get(key)

        if found is not None:
            reused += 1
            if found.name != name:
                renamed += 1
                print(f"  nomi aniqlashtirildi: '{found.name}' -> '{name}'")
                if not dry_run:
                    found.name = name
            continue

        created += 1
        if dry_run:
            print(f"  [dry-run] yangi fakultet: {name}")
            continue
        faculty = Faculty(name=name, course_count=0, student_count=0)
        db.add(faculty)
        await db.flush()
        existing[key] = faculty

    if not dry_run and (created or renamed):
        await db.commit()
    print(
        f"Fakultetlar: {created} ta yangi, {reused} tasi mavjudi ishlatildi"
        + (f", {renamed} tasining nomi aniqlashtirildi" if renamed else "")
    )
    return existing if dry_run else await _faculty_map(db)


async def run(
    dry_run: bool = False,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """session_factory parametr sifatida beriladi, chunki testlar buni
    o'z (vaqtinchalik) bazasida bajaradi. Usiz testlar haqiqiy bazaga
    688 ta qator yozib qo'yardi."""
    stats = Counter()
    async with session_factory() as db:
        faculty_names = {fac for _, _, fac, _ in XODIMLAR if fac}
        faculties = await _ensure_faculties(db, faculty_names, dry_run)

        # Mavjud xodimlarni bir marta o'qib olamiz — 688 ta alohida
        # SELECT o'rniga bitta so'rov.
        result = await db.execute(
            select(StudentStaff).where(StudentStaff.pinfl.is_not(None))
        )
        by_pinfl = {r.pinfl: r for r in result.scalars().all()}

        for pinfl, full_name, fac_name, unit in XODIMLAR:
            faculty = faculties.get(_fac_key(fac_name)) if fac_name else None
            position = unit or "Xodim"
            record = by_pinfl.get(pinfl)

            if record is None:
                stats["yangi"] += 1
                if dry_run:
                    continue
                db.add(
                    StudentStaff(
                        full_name=full_name,
                        type=PERSON_TYPE,
                        pinfl=pinfl,
                        faculty_id=faculty.id if faculty else None,
                        group_or_position=position,
                        biometrics_status="yoq",
                    )
                )
                continue

            # Mavjud qator — faqat bo'sh yoki eskirgan maydonlarni
            # to'ldiramiz. Biometrikaga TEGILMAYDI.
            changed = False
            if record.full_name != full_name:
                record.full_name = full_name
                changed = True
            if faculty is not None and record.faculty_id != faculty.id:
                record.faculty_id = faculty.id
                changed = True
            if record.group_or_position != position:
                record.group_or_position = position
                changed = True
            if record.type != PERSON_TYPE:
                record.type = PERSON_TYPE
                changed = True
            stats["yangilandi" if changed else "o'zgarmadi"] += 1

        if not dry_run:
            await db.commit()

        # Tekshiruv: bazada haqiqatan nechta xodim bor
        total = await db.scalar(
            select(func.count()).select_from(StudentStaff).where(StudentStaff.pinfl.is_not(None))
        )
        confirmed = await db.scalar(
            select(func.count())
            .select_from(StudentStaff)
            .where(StudentStaff.pinfl.is_not(None))
            .where(StudentStaff.biometrics_status == "tasdiqlangan")
        )

    print()
    print("=" * 58)
    print(f"  Faylda            : {len(XODIMLAR)} ta xodim")
    print(f"  Yangi qo'shildi   : {stats['yangi']}")
    print(f"  Yangilandi        : {stats['yangilandi']}")
    unchanged = stats["o" + chr(39) + "zgarmadi"]
    print(f"  O'zgarishsiz      : {unchanged}")
    print("-" * 58)
    print(f"  Bazada jami       : {total} ta JSHSHIRli xodim")
    print(f"  Yuzi tasdiqlangan : {confirmed}")
    print(f"  Tasdiqlanmagan    : {(total or 0) - (confirmed or 0)}")
    print("=" * 58)

    if dry_run:
        print("\n[dry-run] Bazaga hech narsa yozilmadi.")
        return 0

    if total != len(XODIMLAR):
        print(
            f"\nDIQQAT: bazadagi son ({total}) fayldagidan ({len(XODIMLAR)}) farq qiladi.\n"
            "Agar ko'p bo'lsa — ilgari boshqa ro'yxatdan kiritilgan xodimlar bor.\n"
            "Agar kam bo'lsa — yuqoridagi xatolarni ko'rib chiqing."
        )
        return 1

    print("\nHammasi joyida: ro'yxatdagi har bir xodim bazada.")
    return 0


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    sys.exit(asyncio.run(run(dry_run=dry)))
