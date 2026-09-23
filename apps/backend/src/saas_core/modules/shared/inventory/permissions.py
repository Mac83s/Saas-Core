from typing import Final

#: Widzi katalog i stany magazynu firmy.
INVENTORY_READ: Final = "inventory.read"
#: Prowadzi magazyn: przyjmuje, wydaje ludziom, poprawia stany.
INVENTORY_MANAGE: Final = "inventory.manage"
#: Zużywa z własnego zapasu i dobiera produkty do wizyty — bez prowadzenia magazynu.
INVENTORY_USE: Final = "inventory.use"
