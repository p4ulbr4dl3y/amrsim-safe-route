"""Определение рабочего статуса мобильной платформы."""


def determine_status(
    v_odom: float,
    w_odom: float = 0.0,
    is_arrived: bool = False,
    is_lost: bool = False,
    is_stopped: bool = False,
    is_estop: bool = False,
) -> str:
    """Определить рабочий статус мобильной платформы по схеме amr-1.0.

    Возможные статусы:
    - moving;
    - waiting;
    - arrived;
    - lost;
    - estop.

    Параметры:
      v_odom: измеренная линейная скорость по одометрии в м/с;
      w_odom: измеренная угловая скорость по одометрии в рад/с;
      is_arrived: признак успешного прибытия в целевую зону;
      is_lost: признак потери достоверной оценки координат;
      is_stopped: признак намеренной остановки перед препятствием;
      is_estop: признак срабатывания экстренного торможения.

    Возвращает:
      строковый идентификатор статуса платформы.
    """
    if is_arrived:
        return "arrived"
    if is_estop:
        return "estop"

    # При физическом движении колес статус строго moving
    if abs(v_odom) >= 0.05 or abs(w_odom) >= 0.10:
        return "moving"

    # Стационарное состояние платформы при скорости ниже порога 0.05 м/с
    if is_lost:
        return "lost"
    if is_stopped:
        return "waiting"

    return "waiting"
