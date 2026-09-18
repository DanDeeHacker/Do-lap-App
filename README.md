# Došlap — platforma pro monitoring běžecké zátěže a mechaniky

Reálný backend (FastAPI + SQLite) se skutečným přihlášením, čtyřmi oddělenými
rolemi a enginem v0.4 pro monitoring rizikových signálů (interně „injury-risk
engine"). Frontend zůstal beze změny architektury — statické HTML/JS bez
buildu — jen teď mluví se skutečným API místo dat v paměti.

**Pozicování (MDR):** Došlap je nástroj pro monitoring tréninkové zátěže a
běžecké mechaniky a pro podporu rozhodování odborníka — **není zdravotnický
prostředek**, nestanovuje diagnózu ani neurčuje léčbu a nenahrazuje vyšetření.
Skóre je pravděpodobnostní vstup pro fyzioterapeuta, ne predikce ani prognóza
onemocnění. Persistentní disclaimer (`D.MDR_DISCLAIMER` v `core.js`) se
zobrazuje na každé stránce.
