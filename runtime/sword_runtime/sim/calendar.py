"""Deterministic BCE campaign calendar used by Sword & Banners."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
import re

_PATTERN=re.compile(r'^(?P<year>[0-9]{1,4})-BCE-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})T(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})(?P<offset>[+-][0-9]{2}:[0-9]{2})$')
_ANCHOR=5000

@dataclass(frozen=True, order=True)
class CampaignTime:
    """BCE timestamp with deterministic arithmetic and no dependence on wall time."""
    sort_year:int
    month:int
    day:int
    hour:int
    minute:int
    second:int
    offset:str='+08:00'

    @classmethod
    def parse(cls,value:str)->'CampaignTime':
        if not isinstance(value,str): raise TypeError('campaign time must be text')
        m=_PATTERN.fullmatch(value)
        if not m: raise ValueError(f'invalid Sword campaign time: {value!r}')
        bce=int(m.group('year'))
        if bce<=0: raise ValueError('BCE year must be positive')
        mapped=_ANCHOR-bce
        datetime(mapped,int(m.group('month')),int(m.group('day')),int(m.group('hour')),int(m.group('minute')),int(m.group('second')))
        return cls(mapped,int(m.group('month')),int(m.group('day')),int(m.group('hour')),int(m.group('minute')),int(m.group('second')),m.group('offset'))

    @property
    def bce_year(self)->int:
        return _ANCHOR-self.sort_year

    def __str__(self)->str:
        return f'{self.bce_year}-BCE-{self.month:02d}-{self.day:02d}T{self.hour:02d}:{self.minute:02d}:{self.second:02d}{self.offset}'

    def _dt(self)->datetime:
        return datetime(self.sort_year,self.month,self.day,self.hour,self.minute,self.second)

    @classmethod
    def _from_dt(cls,dt:datetime,offset:str)->'CampaignTime':
        if not 1 <= _ANCHOR-dt.year <= 9999: raise ValueError('Sword campaign time leaves supported BCE range')
        return cls(dt.year,dt.month,dt.day,dt.hour,dt.minute,dt.second,offset)

    def add_seconds(self,seconds:int)->'CampaignTime':
        if isinstance(seconds,bool) or not isinstance(seconds,int): raise TypeError('seconds must be integer')
        return self._from_dt(self._dt()+timedelta(seconds=seconds),self.offset)

    def add_hours(self,hours:int)->'CampaignTime':
        return self.add_seconds(hours*3600)

    def add_days(self,days:int)->'CampaignTime':
        return self.add_seconds(days*86400)

    def add_years(self,years:int)->'CampaignTime':
        if isinstance(years,bool) or not isinstance(years,int): raise TypeError('years must be integer')
        target=self.sort_year+years
        day=self.day
        while day>28:
            try:
                dt=datetime(target,self.month,day,self.hour,self.minute,self.second); break
            except ValueError:
                day-=1
        else:
            dt=datetime(target,self.month,day,self.hour,self.minute,self.second)
        return self._from_dt(dt,self.offset)

    def seconds_until(self,other:'CampaignTime')->int:
        if self.offset!=other.offset: raise ValueError('campaign offsets differ')
        return int((other._dt()-self._dt()).total_seconds())
