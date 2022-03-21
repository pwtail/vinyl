# vinyl

Это проект vinyl, который добавляет (нативную) асинхронность в django.

В процессе различных экспериментов выяснилось, что django, вопреки принятому 
мнению, достаточно расширяем и очень даже поддаётся внедрению асинхронности.
Из фич django, которые делают это возможным, можно назвать ленивые кверисеты,
настраиваемость database backend-ов и возможность указать `.using(database)` 
почти везде. Синхронный ввод-вывод вообще - это часть так называемого 
compiler-а, который может быть переопределён в настройках database backend-а. 
Переопределяем в новом compiler-е методы, содержащие ввод-вывод (это 1 метод) 
- и вуаля.

Таким образом, добавление асинхронности решается добавлением новой логической 
базы данных, которая является старой, просто с асинхронным драйвером.

В смысле апи, наиболее легковесным способом показалось сделать отдельный менеджер моделей:

```python
class M(models.Model):
    vinyl = VinylManager()
    objects = Manager()
```

В ветке `universal` содержится proof-of-concept данного подхода, который, 
например, делает возможным следующий код:

```python
[ob, *_] = await MyModel.vinyl.all()
ob.x = 13
await ob.save()
```

proof-of-concept намеренно такой минималистичный по функциональности: целью 
было проверить, насколько легковесным он может быть в смысле интеграции 
с django, в противовес предыдущей версии (форк). Предыдущие версии были 
более навороченными и содержали всю функциональность кверисетов, большинство 
CRUD-операций и ленивые атрибуты.

Однако у реализации есть одна особенность: она содержит синхронную и 
асинхронную версии, выбор которой зависит от динамической настройки 
`IS_ASYNC`. Помимо этого, все возможности django тоже остаются. Таким 
образом, получается, что есть 3 версии django: оригинальный django, аснхронный 
vinyl и 
синхронный vinyl. Это из-за того, что я хотел, чтобы vinyl 
поддерживал как синхронный, так и асинхронный юзкейсы.

Такой подход имеет некоторые накладные расходы: код становится чуть менее 
изящным местами, что может явиться дополнительным препятствием к внешним 
контрибуциям в проект.

Я решил уменьшить скоуп проекта вдвое: оставить только асинхронную версию. 
Следствие этого - если django перестанет существовать, vinyl можно будет 
использовать только для асинхронных сервисов. В остальном же - проект будет 
максимально легковесным и является, на мой взгляд, кратчайшим путём к 
добавлению нативных асинхронных возможностей в django.

Предыдущий код переиспользовать не получится, нужно 
написать новый.