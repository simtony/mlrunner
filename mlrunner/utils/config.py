import yaml
from .misc import color_print


class InvalidYAMLException(Exception):
    pass


def parse_config(config):
    def safe_load(key, dtype, required=False):
        if key not in config and required:
            raise InvalidYAMLException("'{}' should be in the first doc.".format(key))

        value = config.get(key, dtype())
        if not isinstance(value, dtype):
            raise InvalidYAMLException("'{}' should be a {}.".format(key, dtype))

        return value

    templates = safe_load("template", dict, required=True)
    if not templates:
        raise InvalidYAMLException("No template exists.")
    resources = safe_load("resource", list, required=True)

    def not_emtpy_dict(name, obj):
        if not isinstance(obj, dict):
            raise InvalidYAMLException("{} should be a dict, not {}.".format(name, type(obj)))
        else:
            if not obj:
                raise InvalidYAMLException("{} should be a nonempty dict.".format(name))

    # alias:
    #   alias1:
    #     case1: { a: 1, b: 1 }
    #     case2: { a: 2, b: 2 }
    aliases = safe_load("alias", dict)
    for key, value in aliases.items():
        not_emtpy_dict("alias[{}]".format(key), value)
        ks = set()  # params to be filled
        for k, v in value.items():
            not_emtpy_dict("alias[{}][{}]".format(key, k), v)
            current_ks = set(v.keys())
            if not ks:
                ks.update(current_ks)
            elif ks != current_ks:
                raise InvalidYAMLException("All entries in alias[{}][{}] should have the same target keys, "
                                           "found difference: {} and {}".format(key, k, ks, current_ks))

    defaults = safe_load("default", dict)
    return templates, resources, aliases, defaults


def filter_choices(title, choices):
    if not choices:
        raise InvalidYAMLException("No choices available.")
    if title is not None:
        title_unset = True  #
        title_not_exist = True
        temp_choices = []
        for choice in choices:
            if "_title" in choice:
                title_unset = False
                if choice["_title"] == title:
                    title_not_exist = False
                    temp_choices.append(choice)
        choices = temp_choices
        if title_unset:
            raise InvalidYAMLException("'_title' not specified in any choices")
        if title_not_exist:
            raise InvalidYAMLException("'_title'={} not found in any choices".format(title))
        color_print("Run choices with title '{}'".format(title), "green")
        color_print(yaml.dump_all(choices, default_flow_style=True, explicit_start=True), "green")
    for choice in choices:
        if "_title" in choice:
            del choice["_title"]
    return choices


def load_yaml(args):
    # parse yaml file
    with open(args.yaml, "r") as fin:
        docs = list(yaml.load_all(fin, Loader=yaml.FullLoader))
    if not docs:
        raise InvalidYAMLException("empty yaml file.")

    templates, resources, aliases, defaults = parse_config(docs[0])

    if args.resource:
        print("Override resource to {}".format(repr(args.resource)))
        resources = args.resource
    resources = [str(i) for i in resources]
    # we dub each doc specifying a grid sweep of different params a "choice"
    choices = filter_choices(args.title, docs[1:])
    return resources, templates, aliases, defaults, choices
