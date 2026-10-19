# src/palatium_ai/__main__.py

"""``python -m palatium_ai`` — короткая форма ``python -m palatium_ai.main``.

Карта проекта (099) и ``scripts/dev-up.ps1`` называют именно короткую форму, но в пакете
не было ``__main__``: команда падала с
``No module named palatium_ai.__main__; 'palatium_ai' is a package and cannot be directly executed``.

Оба написания обязаны попадать в один лаунчер: ``main()`` владеет фабрикой event loop и
политикой reload, поэтому второй вход с собственным ``uvicorn.run`` разошёлся бы с ними.
"""

from palatium_ai.main import main

if __name__ == "__main__":
    main()
