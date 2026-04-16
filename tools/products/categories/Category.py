# =============================================================================
# tools/products/categories/Category.py
# 产品分类系统模块
#
# 提供两个核心类：
#   CategoryTree - 描述分类体系树形结构（用于前端展示层级）
#   Category     - 继承自 FinRangeParam，将产品划分到命名类别中；
#                  支持 Cat1 * Cat2 创建笛卡尔积组合分类。
#
# 在因子测试中，Category 用于按行业、夜盘时段等维度对产品分组，
# 分别在每个类别内计算 IC 或分组收益。
# =============================================================================
from tools import UniqueObject
from weakref import WeakValueDictionary
from typing import Any, Dict, Optional, Tuple, Type, List

from tools.parameters.Parameter import FinRangeParam

# 类目树中的特殊关键字
object_word = '$OBJECTS$'   # 叶节点的对象列表键
subclass_word = '$SUBCLASS$'  # 子类节点键

class CategoryTree:
    """
    分类树结构描述。

    描述产品类别之间的层级关系（用于前端树形展示）。
    tree 是一个嵌套字典，根节点类型为 type，其子项为各分类名。
    示例：
      tree = {Product: {'$OBJECTS$': [p1, p2], '行业1': {...}, ...}}
    """
    def __init__(self, tree: Dict[Any, Any]):
        self.tree = tree
        assert len(tree) == 1, "The tree should have exactly one root type."
        self.root_type = next(iter(tree.keys()))
        assert isinstance(tree[self.root_type], dict), "The value associated with the root type should be a dictionary."
        if object_word in tree[self.root_type]:
            self.objs = tree[self.root_type][object_word]
            assert isinstance(self.objs, list), f"The value associated with the key '{object_word}' should be a list of objects."
        else:
            self.objs = None

class Category(FinRangeParam):
    """
    产品分类参数。

    基于 FinRangeParam，categories 列表即为合法的分类名称集合。
    提供将产品划分到各类别的接口：
      - is_in_category(catname, obj) : 判断某产品是否属于某类别
      - get_obj_of_catname(...)       : 获取某类别下的所有产品
      - get_catname_of_obj(...)       : 获取某产品所属的类别名
      - Cat1 * Cat2                  : 生成两个分类的笛卡尔积组合分类

    始终包含 'Others' 类别，不属于任何已知类别的产品归入此类。
    """
    _instances = WeakValueDictionary()
    _override_family_root = True  # SerialObject 序列号计数独立于其他类族

    def __new__(cls, alias: str, *args, **kwargs):
        return super().__new__(cls, type_alias='C', alias=alias)

    def __init__(self, alias: str, type: Type[UniqueObject], categories: List[str], *args, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(type_alias='C', alias=alias, value_space=categories, *args, **kwargs)
            self.type = type
            self.categories = categories
            if 'Others' not in self.categories:
                self.categories.append('Others')
            self.whether_is_in_category = lambda catname, obj, *args, **kwargs: \
                self._whether_is_in_category(catname, obj, *args, **kwargs) and\
                catname in self.categories and isinstance(obj, self.type)
            self.parent_categories = []
            self.objs = []

    def _whether_is_in_category(self, catname: str, obj: UniqueObject, *args, **kwargs) -> bool:
        raise NotImplementedError
    
    def is_in_category(self, catname: str, obj: UniqueObject, *args, **kwargs) -> bool:
        assert catname in self.categories, f"Category name '{catname}' is not in the categories of this Category."
        assert isinstance(obj, self.type), f"Object '{obj}' is not of the correct type for this Category."
        return self.whether_is_in_category(catname, obj, *args, **kwargs)
    
    def get_obj_of_catname(self, catname: str, all_objects: List[UniqueObject], *args, **kwargs) -> List[UniqueObject]:
        if catname == 'Others':
            return [obj for obj in all_objects if not any(self.whether_is_in_category(c, obj, *args, **kwargs) for c in self.categories if c != 'Others')]
        return [obj for obj in all_objects if self.whether_is_in_category(catname, obj, *args, **kwargs)]

    def get_catname_of_obj(self, obj: UniqueObject, *args, **kwargs) -> Optional[str]:
        for catname in self.categories:
            if catname == 'Others':
                continue
            if self.whether_is_in_category(catname, obj, *args, **kwargs):
                return catname
        return 'Others'

    def __mul__(self, other: 'Category', all_objects: List[UniqueObject] = []) -> 'Category':
        if isinstance(other, Category):
            all_objects = all_objects if all_objects is not None else list(set(self.objs) & set(other.objs))
            if all_objects and self.whether_contained_in(other, all_objects):
                self.objs = list(set(self.objs) & set(other.objs) & set(all_objects))
                return self
            if all_objects and other.whether_contained_in(self, all_objects):
                other.objs = list(set(self.objs) & set(other.objs) & set(all_objects))
                return other
            if self.type in other.type.__mro__:
                new_type = self.type
            elif other.type in self.type.__mro__:
                new_type = other.type
            else:
                raise ValueError(f"Cannot combine categories with incompatible types: {self.type} and {other.type}")
            new_alias = f"{self.alias}×{other.alias}"
            new_categories = [f"({c1}×{c2})" for c1 in self.categories for c2 in other.categories if c1 != 'Others' and c2 != 'Others']
            new_categories.append('Others')
            def new_whether_is_in_category(catname: str, obj: UniqueObject, *args, **kwargs):
                if catname == 'Others':
                    return not any(self.whether_is_in_category(c1, obj, *args, **kwargs) and other.whether_is_in_category(c2, obj, *args, **kwargs)
                                   for c1 in self.categories for c2 in other.categories if c1 != 'Others' and c2 != 'Others')
                catname_split = catname.strip('()').split('×')
                return self.whether_is_in_category(catname_split[0], obj, *args, **kwargs) \
                    and other.whether_is_in_category(catname_split[1], obj, *args, **kwargs)
            new_cat = Category(alias=new_alias, type=new_type, categories=new_categories)
            new_cat.whether_is_in_category = new_whether_is_in_category
            new_cat.parent_categories = [self, other]
            left_get_value_alias = self.get_value_alias
            right_get_value_alias = other.get_value_alias
            def new_get_value_alias(x: str) -> str:
                if x == 'Others':
                    return 'Others'
                x_split = x.strip('()').split('×')
                return f"({left_get_value_alias(x_split[0])}×{right_get_value_alias(x_split[1])})"
            new_cat.get_value_alias = new_get_value_alias
            if all_objects:
                new_cat.objs = all_objects
            else:
                new_cat.objs = list(set(self.objs) & set(other.objs))
            return new_cat
        else:
            raise TypeError(f"Unsupported operand type(s) for *: 'Category' and '{type(other).__name__}'")
        
    def mul_under_objs(self, other: 'Category', all_objects: List[UniqueObject]) -> 'Category':
        return self.__mul__(other, all_objects=all_objects)
        
    def whether_contained_in(self, other: 'Category', all_objects: List[UniqueObject]) -> bool:
        if self.type not in other.type.__mro__:
            return False
        for catname in self.categories:
            if catname == 'Others':
                continue
            objs_of_catname = self.get_obj_of_catname(catname, all_objects)
            for other_catname in other.categories:
                if other_catname == 'Others':
                    continue
                if all(not other.whether_is_in_category(other_catname, obj) for obj in objs_of_catname):
                    continue
                if not all(other.whether_is_in_category(other_catname, obj) for obj in objs_of_catname):
                    return False
        return True
    
    def get_tree_with_parents(self, all_objects: Optional[List[UniqueObject]] = None, word: str = object_word,
                              ancester: Optional[Type[UniqueObject]] = None) -> CategoryTree:
        res, _ = self._get_tree_with_parents(all_objects=all_objects, word=word, ancester=ancester)
        return res
        
    def _get_tree_with_parents(self, all_objects: Optional[List[UniqueObject]] = None, word: str = object_word,
                              ancester: Optional[Type[UniqueObject]] = None) -> Tuple[CategoryTree, List[Any]]:
        if all_objects is None:
            all_objects = self.objs
        if not self.parent_categories:
            res, list = self._get_tree(all_objects=all_objects, word=word, ancester=ancester)
            return res, [list]
        assert self.parent_categories, "This method should only be called for categories with parent categories."
        assert len(self.parent_categories) == 2, "This method currently only supports categories with exactly two parent categories."
        assert isinstance(self.parent_categories[0], Category) and isinstance(self.parent_categories[1], Category), "Parent categories should be instances of Category."
        Tree1, list1 = self.parent_categories[0]._get_tree_with_parents(all_objects, word, ancester)
        Tree2, list2 = self.parent_categories[1]._get_tree_with_parents(all_objects, word, ancester)
        Tree = combine_trees(Tree1, Tree2, word)
        list1parent = [self.parent_categories[1]] * len(list1)
        list2parent = [self.parent_categories[0]] * len(list2)
        list = []
        for thislist, parent in zip(list1 + list2, list1parent + list2parent):
            tree = Tree.tree
            for item in thislist:
                tree = tree[item]
            for key in tree.keys():
                assert key != word, f"The tree should not contain the key '{word}' for categories."
                assert word in tree[key], f"The tree should contain the key '{word}' for objects."
                subTree, sublist = parent._get_tree(all_objects=tree[key][word], word=word)
                subtree = subTree.tree
                for item in sublist:
                    subtree = subtree[item]
                tree[key][parent.alias] = subtree
                list.append(thislist + [parent.alias])
        return Tree if ancester is None else _climb_to_ancester(Tree, ancester, word), list

    def get_tree(self, all_objects: Optional[List[UniqueObject]] = None, word: str = object_word,
                 ancester: Optional[Type[UniqueObject]] = None, *args, **kwargs) -> CategoryTree:
        res, _ = self._get_tree(all_objects=all_objects, word=word, ancester=ancester)
        return res

    def _get_tree(self, all_objects: Optional[List[UniqueObject]] = None, word: str = object_word,
                  ancester: Optional[Type[UniqueObject]] = None, *args, **kwargs) -> Tuple[CategoryTree, List[Any]]:
        if all_objects is None:
            all_objects = self.objs
        tree = {}
        for obj in all_objects:
            for catname in self.categories:
                if self.whether_is_in_category(catname, obj):
                    catname_alias = self.get_value_alias(catname)
                    tree.setdefault(catname_alias, {}).setdefault(word, []).append(obj)
        Tree = CategoryTree({self.type: {self.alias: tree, word: all_objects}})
        list = [self.type, self.alias]
        if ancester is not None:
            for parent_cls in self.type.__mro__[1:]:
                list = [parent_cls, subclass_word] + list
                if parent_cls == ancester:
                    break
        return Tree if ancester is None else _climb_to_ancester(Tree, ancester, word), list
    
    def get_tree_with_parents_without_products(self, word: str = object_word,
                              ancester: Optional[Type[UniqueObject]] = None) -> CategoryTree:
        res, _ = self._get_tree_with_parents_without_products(word=word, ancester=ancester)
        return res

    def _get_tree_with_parents_without_products(self, word: str = object_word,
                              ancester: Optional[Type[UniqueObject]] = None) -> Tuple[CategoryTree, List[Any]]:
        if not self.parent_categories:
            res, list = self._get_tree_without_products(word=word, ancester=ancester)
            return res, [list]
        assert self.parent_categories, "This method should only be called for categories with parent categories."
        assert len(self.parent_categories) == 2, "This method currently only supports categories with exactly two parent categories."
        assert isinstance(self.parent_categories[0], Category) and isinstance(self.parent_categories[1], Category), "Parent categories should be instances of Category."
        Tree1, list1 = self.parent_categories[0]._get_tree_with_parents_without_products(word=word, ancester=ancester)
        Tree2, list2 = self.parent_categories[1]._get_tree_with_parents_without_products(word=word, ancester=ancester)
        Tree = combine_trees(Tree1, Tree2, word)
        list1parent = [self.parent_categories[1]] * len(list1)
        list2parent = [self.parent_categories[0]] * len(list2)
        list = []
        for thislist, parent in zip(list1 + list2, list1parent + list2parent):
            tree = Tree.tree
            for item in thislist:
                tree = tree[item]
            for key in tree.keys():
                assert key != word, f"The tree should not contain the key '{word}' for categories."
                assert word in tree[key], f"The tree should contain the key '{word}' for objects."
                subTree, sublist = parent._get_tree_without_products(word=word)
                subtree = subTree.tree
                for item in sublist:
                    subtree = subtree[item]
                tree[key][parent.alias] = subtree
                list.append(thislist + [parent.alias])
        return Tree if ancester is None else _climb_to_ancester(Tree, ancester, word), list
    
    def get_tree_without_products(self, word: str = object_word,
            ancester: Optional[Type[UniqueObject]] = None, *args, **kwargs) -> CategoryTree:
        res, _ = self._get_tree_without_products(word=word, ancester=ancester, *args, **kwargs)
        return res
    
    def _get_tree_without_products(self, word: str = object_word,
            ancester: Optional[Type[UniqueObject]] = None, *args, **kwargs) -> Tuple[CategoryTree, List[Any]]:
        tree = {}
        for catname in self.categories:
            catname_alias = self.get_value_alias(catname)
            tree.setdefault(catname_alias, {}).setdefault(word, [])
        Tree = CategoryTree({self.type: {self.alias: tree, word: []}})
        list = [self.type, self.alias]
        if ancester is not None:
            for parent_cls in self.type.__mro__[1:]:
                list = [parent_cls, subclass_word] + list
                if parent_cls == ancester:
                    break
        return Tree if ancester is None else _climb_to_ancester(Tree, ancester, word), list
        
def _climb_to_ancester(Tree: CategoryTree, ancester: Type[UniqueObject], word: str = object_word) -> CategoryTree:
    tree = Tree.tree
    if ancester in tree:
        return Tree
    assert len(tree.keys()) == 1, "First of the tree should have exactly one key (the class type)."
    key = next(iter(tree.keys()))
    assert word in tree[key], f"The tree should contain the key '{word}' for objects."
    objs = tree[key][word]
    assert isinstance(objs, list), f"The value associated with the key '{word}' should be a list of objects."
    assert ancester in key.__mro__, f"Ancester type '{ancester}' is not in the MRO of the category's type '{key}'."
    for parent_cls in key.__mro__[1:]:
        tree = {parent_cls: {subclass_word: tree, word: objs}}
        if parent_cls == ancester:
            return CategoryTree(tree)
    raise ValueError(f"Ancester type '{ancester}' is not in the MRO of the category's type '{key}'.")

def combine_trees(Tree1: CategoryTree, Tree2: CategoryTree, word: str = object_word) -> CategoryTree:
    tree1 = Tree1.tree
    tree2 = Tree2.tree
    key1 = next(iter(tree1.keys()))
    key2 = next(iter(tree2.keys()))
    if key1 != key2:
        if key1 in key2.__mro__:
            Tree2 = _climb_to_ancester(Tree2, key1, word)
            return combine_trees(Tree1, Tree2, word)
        elif key2 in key1.__mro__:
            Tree1 = _climb_to_ancester(Tree1, key2, word)
            return combine_trees(Tree1, Tree2, word)
        else:
            for parent_cls in key1.__mro__:
                if parent_cls in key2.__mro__:
                    Tree1 = _climb_to_ancester(Tree1, parent_cls, word)
                    Tree2 = _climb_to_ancester(Tree2, parent_cls, word)
                    return combine_trees(Tree1, Tree2, word)
            raise ValueError(f"Cannot combine trees with incompatible root types: '{key1}' and '{key2}'")
    combined_tree = {}
    key = key1
    for subkey in tree1[key].keys() | tree2[key].keys():
        if subkey == word:
            if key == 'Others':
                combined_tree[word] = list(set(tree1[key][subkey]) & set(tree2[key][subkey]))
            else:
                combined_tree[word] = list(set(tree1[key][subkey]) | set(tree2[key][subkey]))
        elif subkey in tree1[key].keys() & tree2[key].keys():
            subtree1 = CategoryTree({subkey: tree1[key][subkey]})
            subtree2 = CategoryTree({subkey: tree2[key][subkey]})
            combined_tree[subkey] = combine_trees(subtree1, subtree2, word).tree[subkey]
        elif subkey in tree1[key].keys():
            combined_tree[subkey] = tree1[key][subkey]
        else:
            combined_tree[subkey] = tree2[key][subkey]
    return CategoryTree({key: combined_tree})
        
if __name__ == "__main__":
    Cat1 = Category(alias='Cat1', type=UniqueObject, categories=['A', 'B'])
    Cat1.whether_is_in_category = lambda catname, obj, *args, **kwargs: obj.alias.startswith(catname) and catname in Cat1.categories
    Cat2 = Category(alias='Cat2', type=UniqueObject, categories=['X', 'Y'])
    Cat2.whether_is_in_category = lambda catname, obj, *args, **kwargs: obj.alias.endswith(catname) and catname in Cat2.categories
    Cat3 = Cat1 * Cat2

    obj1 = UniqueObject(name='A1X')
    obj2 = UniqueObject(name='B2Y')
    obj3 = UniqueObject(name='A3Y')
    obj4 = UniqueObject(name='B4X')

    print(Cat3.whether_is_in_category('(A×X)', obj1))  # True
    print(Cat3.whether_is_in_category('(B×Y)', obj2))  # True
    print(Cat3.whether_is_in_category('(A×Y)', obj1))  # False
    print(Cat3.whether_is_in_category('(B×X)', obj2))  # False

    Cat4 = Cat1.mul_under_objs(Cat2, all_objects=[obj1, obj2, obj3, obj4])
    Cat5 = Cat3.mul_under_objs(Cat2, all_objects=[obj1, obj2, obj3, obj4])
    Cat6 = Cat1.mul_under_objs(Cat3, all_objects=[obj1, obj2])
    
    print(Cat5 == Cat3)  # True
    print(Cat6 == Cat1)  # True
