package com.example.simplekanyewest.Dto;

import com.example.simplekanyewest.Entity.Memo;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class MemoRequestDto {
    private String title;
    private String content;

    public Memo toEntity() {
        return Memo.builder()
                .title(title)
                .content(content)
                .build();
    }
}

