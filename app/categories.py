"""Grupowanie kategorii sprzedawców (mrch_catg_nm) w grupy tematyczne do oceny handlu.

Kategorie spoza słownika trafiają do grupy "Inne". Mapowanie opiera się na nazwach
z danych (314 kategorii, top 100 pokrywa ok. 99% transakcji).
"""

ONLINE = "Handel internetowy"
OTHER = "Inne"

# Grupy pomijane przy wskaźnikach różnorodności lokalnego handlu:
# sprzedawcy internetowi są przypisani do siedziby firmy, nie do miejsca zakupu.
EXCLUDED_FROM_LOCAL = {ONLINE, OTHER}

_GROUPS: dict[str, list[str]] = {
    "Żywność": [
        "GROCERY STORES/SUPERMARKETS", "MISC FOOD STORES - DEFAULT", "BAKERIES",
        "CANDY/NUT/CONFECTION STORES", "FREEZER/MEAT LOCKERS", "DAIRY PRODUCT STORES",
        "PKG STORES/BEER/WINE/LIQUOR",
    ],
    "Dyskonty i domy towarowe": [
        "DISCOUNT STORES", "VARIETY STORES", "DEPARTMENT STORES", "MISC GENERAL MERCHANDISE",
        "WHOLESALE CLUBS",
    ],
    "Gastronomia": [
        "EATING PLACES AND RESTAURANTS", "FAST FOOD RESTAURANTS", "BARS/TAVERNS/LOUNGES/DISCOS",
        "CATERERS",
    ],
    "Zdrowie i apteki": [
        "DRUG STORES & PHARMACIES", "MED/HEALTH SERVICES - DEF", "DOCTORS & PHYSICIANS",
        "DENTISTS/ORTHODONTISTS", "OPTICIANS", "HOSPITALS", "DENTAL/LAB/MED EQUIPMENT",
        "DRUGS/DRUGGISTS SUNDRIES",
    ],
    "Uroda": [
        "COSMETIC STORES", "BEAUTY/BARBER SHOPS", "HEALTH & BEAUTY SPAS",
    ],
    "Moda i akcesoria": [
        "FAMILY CLOTHING STORES", "MENS/WOMENS CLOTHING STORES", "SHOE STORES",
        "CHILDREN/INFANTS WEAR STORES", "WOMENS READY TO WEAR STORES", "WOMENS ACCESS/SPECIALTY",
        "SPORTS/RIDING APPAREL STORES", "MEN/BOYS CLOTHING/ACC STORES", "MISC APPAREL/ACCESS STORES",
        "LUGGAGE/LEATHER STORES", "JEWELRY STORES",
    ],
    "Dom, ogród i budowa": [
        "HOME SUPPLY WAREHOUSE STORES", "LUMBER/BUILD. SUPPLY STORES", "FURNITURE/EQUIP STORES",
        "NURSERIES, LAWN/GARDEN SUPPLY", "MISC HOME FURNISHING SPECIALTY", "HOUSEHOLD APPLIANCE STORES",
        "HARDWARE STORES", "GLASS/PAINT/WALLPAPER STORES", "CONSTRUCTION MATERIALS - DEF",
        "PLUMBING/HEATING EQUIPMENT", "ELECTRICAL PARTS/EQUIPMENT", "HARDWARE EQUIPMENT/SUPPLIES",
        "FABRIC STORES", "FLORIST SUPPLIES/NURSERY STOCK",
    ],
    "Elektronika i media": [
        "ELECTRONICS STORES", "TELECOMMUNICATION EQUIPMENT", "COMPUTER SOFTWARE STORES",
    ],
    "Motoryzacja i paliwa": [
        "SERVICE STATIONS", "AUTOMATED FUEL DISPENSERS", "FUEL DEALERS", "CAR WASHES",
        "AUTOMOTIVE PARTS STORES", "AUTO SERVICE SHOPS/NON DEALER", "CAR & TRUCK DEALERS/NEW/USED",
        "ELECTRIC VEHICLE CHARGING", "AUTOMOBILE RENTAL AGENCY",
    ],
    "Transport i parkowanie": [
        "LOCAL COMMUTER TRANSPORT", "PARKING LOTS,METERS,GARAGES", "TAXICABS/LIMOUSINES",
        "TOLLS AND BRIDGE FEES", "TRANSPORTATION SVCS - DEFAULT", "PASSENGER RAILWAYS", "BUS LINES",
    ],
    "Turystyka i nocleg": [
        "HOTELS/MOTELS/RESORTS", "TOURIST ATTRACTIONS AND XHBT", "AMUSEMENT PARKS/CIRCUS",
        "TRAVEL AGENCIES", "DUTY FREE STORES", "SPORTING/RECREATIONAL CAMPS",
    ],
    "Rozrywka i sport": [
        "RECREATION SERVICES", "MEMBER CLUBS/SPORT/REC/GOLF", "SPORTING GOODS STORES",
        "BETTING/TRACK/CASINO/LOTTO", "GOVT-OWNED LOTTERIES (NON-US)", "MOTION PICTURE THEATRES",
        "HOBBY, TOY & GAME STORES", "BOWLING ALLEYS", "VIDEO GAME ARCADES/ESTABLISH",
        "COMMERCIAL/PRO SPORTS", "THEATRICAL PRODUCERS", "BICYCLE SHOPS/SALES/SERVICE",
    ],
    "Usługi i administracja": [
        "TELECOMMUNICATION SERVICES", "CABLE, SAT, PAY TV/RADIO SVCS", "UTILITIES/ELEC/GAS/H2O/SANI",
        "COURIER SERVICES", "TAX PAYMENTS", "GOV'T SERV - DEFAULT", "INSURANCE SALES/UNDERWRITE",
        "FINANCIAL INST/MERCHANDISE", "WIRE TRANSFER MONEY ORDER", "PROFESSIONAL SERVICES - DEF",
        "BUSINESS SERVICES - DEFAULT", "ADVERTISING SERVICES", "LAUNDRIES-FAMILY/COMMERCIAL",
        "QUICK COPY/REPRO SERVICES", "PHOTO STUDIOS", "MISC PERSONAL SERV - DEF",
        "CHARITABLE/SOC SERVICE ORGS", "MEMBER ORGANIZATIONS - DEF", "SCHOOLS - DEFAULT",
        "VETERINARY SERVICES", "COMPUTER PROGRAM/SYS DESIGN", "BUYING/SHOPPING SERVICES",
        "DIRECT SELL/DOOR-TO-DOOR", "NON-FIN INST/FC/MO/TC", "PUBLIC WAREHOUSING",
        "CHEMICALS/ALLIED PRODS - DEF",
    ],
    ONLINE: [
        "ONLINE MARKETPLACES", "LARGE DIGITAL GOODS MERCHANT", "DIGITAL GOODS BOOKSMOVIEMUSIC",
    ],
    "Pozostały detal": [
        "NEWS DEALERS/NEWSSTANDS", "CIGAR STORES/STANDS", "BOOK STORES", "PET STORES/FOOD & SUPPLY",
        "GIFT, CARD, NOVELTY STORES", "STATIONERY STORES", "STATIONERY/OFFICE SUPPLIES",
        "MISC SPECIALTY RETAIL", "USED MERCHANDISE STORES", "RELIGIOUS GOODS STORES", "FLORISTS",
        "MISC PUBLISHING & PRINTING", "BOOKS/PERIODICALS/NEWSPAPERS",
    ],
}

CATEGORY_TO_GROUP: dict[str, str] = {
    cat: group for group, cats in _GROUPS.items() for cat in cats
}

GROUP_ORDER: list[str] = list(_GROUPS) + [OTHER]


def group_of(category: str) -> str:
    return CATEGORY_TO_GROUP.get(category, OTHER)


GROUP_ICONS: dict[str, str] = {
    "Żywność": "🛒", "Dyskonty i domy towarowe": "🏬", "Gastronomia": "🍽️", "Zdrowie i apteki": "💊",
    "Uroda": "💄", "Moda i akcesoria": "👗", "Dom, ogród i budowa": "🔨", "Elektronika i media": "💻",
    "Motoryzacja i paliwa": "⛽", "Transport i parkowanie": "🚌", "Turystyka i nocleg": "🏨",
    "Rozrywka i sport": "🎭", "Usługi i administracja": "🧾", ONLINE: "🌐",
    "Pozostały detal": "🛍️", OTHER: "❔",
}


def labeled(group: str) -> str:
    """Nazwa grupy z ikoną, do etykiet na wykresach."""
    return f"{GROUP_ICONS.get(group, '')} {group}".strip()
