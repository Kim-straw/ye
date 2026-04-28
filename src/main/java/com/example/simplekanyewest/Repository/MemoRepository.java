package com.example.simplekanyewest.Repository;

import com.example.simplekanyewest.Entity.Memo;
import org.springframework.data.jpa.repository.JpaRepository;

public interface MemoRepository extends JpaRepository<Memo, Long> {
}