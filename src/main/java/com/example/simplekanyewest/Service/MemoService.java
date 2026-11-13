package com.example.simplekanyewest.Service;

import com.example.simplekanyewest.Dto.MemoRequestDto;
import com.example.simplekanyewest.Entity.Memo;
import com.example.simplekanyewest.Repository.MemoRepository;
import lombok.AllArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@AllArgsConstructor

public class MemoService {
    private final MemoRepository memoRepository;

    public Memo createMemo(MemoRequestDto request) {
        Memo memo = request.toEntity();
        return memoRepository.save(memo);
    }
}