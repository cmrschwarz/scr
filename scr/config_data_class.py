from typing import Any, Optional, Callable


class ConfigDataClass:
    _config_slots_: list[str] = []
    _subconfig_slots_: list[str] = []
    _final_values_: set[str]
    _value_sources_: dict[str, str]

    def __init__(self, blank: bool = False) -> None:
        self._final_values_ = set()
        self._value_sources_ = {}
        if not blank:
            return
        for k in self.__class__._config_slots_:
            self.__dict__[k] = None

    @staticmethod
    def _previous_annotations_as_config_slots(
        annotations: dict[str, Any],
        subconfig_slots: list[str]
    ) -> list[str]:
        subconfig_slots_dict = set(subconfig_slots + ["__annotations__"])
        return list(k for k in annotations.keys() if k not in subconfig_slots_dict)

    def apply_defaults(self, defaults: 'ConfigDataClass') -> None:
        for cs in self.__class__._config_slots_:
            if cs in defaults.__dict__:
                def_val = defaults.__dict__[cs]
            else:
                def_val = defaults.__class__.__dict__[cs]
            if cs not in self.__dict__ or self.__dict__[cs] is None:
                self.__dict__[cs] = def_val
                vs = defaults._value_sources_.get(cs, None)
                if vs:
                    self._value_sources_[cs] = vs

        for scs in self.__class__._subconfig_slots_:
            self.__dict__[scs].apply_defaults(defaults.__dict__[scs])

    def follow_attrib_path(self, attrib_path: list[str]) -> tuple['ConfigDataClass', str]:
        assert len(attrib_path)
        conf = self
        for attr in attrib_path[:-1]:
            assert attr in conf._subconfig_slots_
            conf = conf.__dict__[attr]
        attr = attrib_path[-1]
        assert attr in conf._config_slots_
        return conf, attr

    def resolve_attrib_path(
        self, attrib_path: list[str],
        transform: Optional[Callable[[Any], Any]] = None
    ) -> Any:
        conf, attr = self.follow_attrib_path(attrib_path)
        if attr in conf.__dict__:
            val = conf.__dict__[attr]
            if transform:
                val = transform(val)
                conf.__dict__[attr] = val
            return val
        val = conf.__class__.__dict__[attr]
        if transform:
            val = transform(val)
            conf.__class__.__dict__[attr] = val
        return val

    def has_custom_value(self, attrib_path: list[str]) -> bool:
        conf, attr = self.follow_attrib_path(attrib_path)
        return attr in conf._value_sources_

    def get_configuring_argument(self, attrib_path: list[str]) -> Optional[str]:
        conf, attr = self.follow_attrib_path(attrib_path)
        return conf._value_sources_.get(attr, None)

    def try_set_config_option(self, attrib_path: list[str], value: Any, arg: str) -> Optional[str]:
        conf, attr = self.follow_attrib_path(attrib_path)
        if attr in conf._final_values_:
            return conf._value_sources_[attr]
        conf._final_values_.add(attr)
        conf._value_sources_[attr] = arg
        conf.__dict__[attr] = value
        return None
